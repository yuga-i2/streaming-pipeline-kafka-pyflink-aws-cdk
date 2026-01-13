"""
Data models for e-commerce order processing pipeline.

This module defines schemas for order events at different stages:
1. OrderEvent: Raw input from checkout system (Kafka source)
2. EnrichedOrder: After validation and enrichment
3. OrderValidationError: Failed validation records (DLQ sink)
4. OrderAggregation: Windowed metrics for analytics

Design Notes:
- All classes are Python dataclasses with JSON serialization support
- BigDecimal precision for financial amounts (critical for correctness)
- Event-time semantics: timestamp field used for watermarking
- DLQ pattern: Separated from main stream via side outputs
"""

from dataclasses import dataclass, asdict, field
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
import json


# ============================================================================
# INPUT SCHEMA: Raw order from checkout system
# ============================================================================

@dataclass
class OrderEvent:
    """
    Represents a raw order event from the e-commerce checkout system.
    
    This is the INPUT contract: what arrives on ecommerce.orders.raw topic.
    
    Fields:
        order_id: Unique order identifier (UUID or sequential)
        customer_id: Customer identifier for enrichment
        amount: Order total in the specified currency
                → Use Decimal, NOT float (floating-point arithmetic loses precision)
                → Example: $10.10 becomes 10.100000001 in float, incorrect for money
        currency: ISO 4217 code (USD, EUR, GBP, etc.)
        status: Order status from checkout (e.g., 'confirmed', 'pending_payment')
        timestamp: Event timestamp (ISO-8601) for watermarking
                  → Parsed as event-time, not processing-time
                  → Flink uses this for windowing and late arrival detection
        items_count: Number of items in order (for correlation with items topic)
    
    Example JSON:
        {
            "order_id": "ORD-20250113-001234",
            "customer_id": "CUST-789456",
            "amount": "149.99",
            "currency": "USD",
            "status": "confirmed",
            "timestamp": "2025-01-13T15:30:45.123Z",
            "items_count": 3
        }
    """
    order_id: str
    customer_id: str
    amount: Decimal  # Use Decimal for financial precision
    currency: str
    status: str
    timestamp: str  # ISO-8601 format (e.g., "2025-01-13T15:30:45.123Z")
    items_count: int

    def to_json(self) -> str:
        """Serialize to JSON for Kafka."""
        data = asdict(self)
        # Convert Decimal to string (JSON-safe)
        data['amount'] = str(self.amount)
        return json.dumps(data)

    @staticmethod
    def from_json(json_str: str) -> 'OrderEvent':
        """Deserialize from Kafka JSON."""
        data = json.loads(json_str)
        data['amount'] = Decimal(data['amount'])
        return OrderEvent(**data)


# ============================================================================
# OUTPUT SCHEMA: After validation, enrichment, and processing
# ============================================================================

@dataclass
class EnrichedOrder:
    """
    Represents an order after passing validation and enrichment processing.
    
    This is the OUTPUT contract: what is written to ecommerce.orders.processed topic.
    
    This schema extends OrderEvent with enrichment fields that were added during
    processing. Kept separate from OrderEvent to enable independent schema evolution:
    - Upstream (checkout) can add fields without breaking our processing
    - Downstream (analytics) can expect consistent enrichment fields
    
    Enrichment Fields (added by order processor):
        region: Geographic region derived from customer_id (e.g., 'us-west-2', 'eu-central-1')
               → Enables regional windowed aggregations
               → Derived from customer_id lookup table or cache
        tax: Calculated tax amount based on region + order amount
             → Region-specific tax rates (VAT in EU, sales tax varies by US state)
             → Applied to enable regulatory compliance reporting
        order_value_category: Binned category for business intelligence
                             → Values: "small" (<$50), "medium" ($50-$500), "large" (>$500)
                             → Enables quick filtering for anomaly detection (unusual spike in large orders)
        merchant_id: Assigned merchant for transaction settlement
                    → Enriched via broadcast state (external table lookup)
        processed_at: Timestamp when this order was processed by Flink
                     → For operational tracking and SLA monitoring
        processing_duration_ms: Time spent in the processing pipeline
                               → Detects bottlenecks; alerts if >1000ms
    
    Processing Guarantees:
        - ALL fields in the INPUT schema are preserved (no data loss)
        - Exactly-one processing: Same order never duplicated (verified by order_id state)
        - Event-time semantics: Timestamp from OrderEvent drives windowing, not processing time
    
    Example JSON (output):
        {
            "order_id": "ORD-20250113-001234",
            "customer_id": "CUST-789456",
            "amount": "149.99",
            "currency": "USD",
            "status": "confirmed",
            "timestamp": "2025-01-13T15:30:45.123Z",
            "items_count": 3,
            "region": "us-west-2",
            "tax": "12.49",
            "order_value_category": "medium",
            "merchant_id": "MERCH-US-001",
            "processed_at": "2025-01-13T15:30:46.234Z",
            "processing_duration_ms": 1091
        }
    """
    # Original OrderEvent fields (preserved)
    order_id: str
    customer_id: str
    amount: Decimal
    currency: str
    status: str
    timestamp: str
    items_count: int

    # Enrichment fields (added during processing)
    region: str
    tax: Decimal
    order_value_category: str  # "small", "medium", "large"
    merchant_id: str
    processed_at: str  # ISO-8601
    processing_duration_ms: int

    def to_json(self) -> str:
        """Serialize to JSON for Kafka."""
        data = asdict(self)
        data['amount'] = str(self.amount)
        data['tax'] = str(self.tax)
        return json.dumps(data)

    @staticmethod
    def from_json(json_str: str) -> 'EnrichedOrder':
        """Deserialize from JSON."""
        data = json.loads(json_str)
        data['amount'] = Decimal(data['amount'])
        data['tax'] = Decimal(data['tax'])
        return EnrichedOrder(**data)


# ============================================================================
# DLQ SCHEMA: Failed validation records (side output)
# ============================================================================

@dataclass
class OrderValidationError:
    """
    Represents an order that failed validation and was routed to the Dead Letter Queue.
    
    This schema enables operational visibility: we don't silently drop bad data.
    
    The DLQ pattern is critical for production systems:
    - Customers can see why their order failed
    - Ops can replay failed records after fixing issues
    - Metrics on failure rates alert us to data quality problems
    
    Error Classifications:
        SCHEMA_INVALID: Missing required fields or wrong data types
                       Example: "order_id" is missing, or "amount" is not a number
                       → Indicates upstream schema changes (breaking change from checkout)
        BUSINESS_RULE_VIOLATION: Valid schema but business logic rejects it
                                Example: amount < 0, invalid currency code, unknown status
                                → May be fraud, bad input, or legitimate edge case (refund)
        DUPLICATE: Order with same order_id already processed within deduplication window
                  → Caused by: network retries, checkout resubmission, distributed trace ID collision
                  → Recovery: Idempotent processing ensures no double-charging
        TIMEOUT: Processing took too long (exceeded configured timeout)
                → Rare, indicates system overload or infinite loop in enrichment logic
    
    Fields:
        original_message: Raw JSON as received from Kafka (truncated if >10KB)
                         → Enables exact reproduction of issue for debugging
        error_type: Classification of the error (see above)
        error_message: Human-readable explanation of what went wrong
                      Example: "Field 'amount' missing from JSON"
        error_timestamp: When the error occurred (Flink processing time, not event time)
        attempted_order_id: Best-effort extraction of order_id (may be null if schema is completely broken)
                           → For correlating with customer service tickets
    
    Example JSON (to DLQ topic):
        {
            "original_message": "{\"order_id\": \"ORD-001\", ...malformed...}",
            "error_type": "SCHEMA_INVALID",
            "error_message": "Field 'amount' is not a valid number: 'NaN'",
            "error_timestamp": "2025-01-13T15:30:46.234Z",
            "attempted_order_id": "ORD-001"
        }
    """
    original_message: str  # Truncated if > 10KB (prevent DLQ topic explosion)
    error_type: str  # "SCHEMA_INVALID", "BUSINESS_RULE_VIOLATION", "DUPLICATE", "TIMEOUT"
    error_message: str
    error_timestamp: str  # ISO-8601, Flink processing time
    attempted_order_id: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON for DLQ topic."""
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(json_str: str) -> 'OrderValidationError':
        """Deserialize from JSON."""
        data = json.loads(json_str)
        return OrderValidationError(**data)


# ============================================================================
# METRICS SCHEMA: Windowed aggregations for analytics
# ============================================================================

@dataclass
class OrderAggregation:
    """
    Represents aggregated order metrics over a 5-minute tumbling window.
    
    This schema is used for ANALYTICS and MONITORING, not transactions.
    
    Windowing Strategy:
        Type: Tumbling (non-overlapping, 5-minute fixed windows)
        Time: Event-time (based on order timestamp, not processing time)
        Watermark: 10-minute allowed lateness
                  → Orders arriving >10min late are routed to side output (late events)
                  → Enables balancing freshness (5min) vs completeness (allow 10min lag)
        Key: region (all orders in us-west-2 go to one window, eu-central-1 to another)
    
    Example: 5 orders arrive from 15:25:00 - 15:30:00 in us-west-2 region
        window_start: 2025-01-13T15:25:00Z
        window_end: 2025-01-13T15:30:00Z
        region: us-west-2
        total_orders: 5
        total_amount: Decimal("724.95")
        avg_order_value: Decimal("144.99")
        max_order_value: Decimal("299.99")
        processing_timestamp_ms: 1673612400123  # When Flink processed this window
    
    Use Cases:
        1. Dashboard: Regional order volumes (detect regional outages)
        2. Alerting: Spike detection (5x normal volume in 5min = possible fraudulent activity)
        3. Billing: Reconciliation counts (did all orders from 15:25-15:30 get charged?)
        4. ML Input: Feature engineering for anomaly detection (historical order patterns)
    
    Note: This is a ROLLING METRIC, not a transaction record.
        → Never use for accounting (use raw OrderEvent instead)
        → Use for operational dashboards and anomaly detection
    """
    region: str
    total_orders: int
    total_amount: Decimal  # Sum of all order amounts in window
    avg_order_value: Decimal  # total_amount / total_orders
    max_order_value: Decimal  # Maximum single order in window
    window_start: str  # ISO-8601, e.g., "2025-01-13T15:25:00Z"
    window_end: str  # ISO-8601, e.g., "2025-01-13T15:30:00Z"
    processing_timestamp_ms: int  # When Flink emitted this (for latency monitoring)

    def to_json(self) -> str:
        """Serialize to JSON for metrics topic."""
        data = asdict(self)
        data['total_amount'] = str(self.total_amount)
        data['avg_order_value'] = str(self.avg_order_value)
        data['max_order_value'] = str(self.max_order_value)
        return json.dumps(data)

    @staticmethod
    def from_json(json_str: str) -> 'OrderAggregation':
        """Deserialize from JSON."""
        data = json.loads(json_str)
        data['total_amount'] = Decimal(data['total_amount'])
        data['avg_order_value'] = Decimal(data['avg_order_value'])
        data['max_order_value'] = Decimal(data['max_order_value'])
        return OrderAggregation(**data)
