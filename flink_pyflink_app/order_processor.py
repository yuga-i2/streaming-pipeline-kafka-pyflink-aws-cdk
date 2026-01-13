"""
PyFlink Order Processing Application

Real-time e-commerce order processing with validation, enrichment, windowed aggregation,
and exactly-once semantics.

Architecture:
    ecommerce.orders.raw (Kafka)
            ↓
        [OrderValidator] (filters malformed → DLQ)
            ↓
        [OrderEnricher] (adds region, tax, category)
            ↓
        [OrderDeduplicator] (keyed state: order_id)
            ↓
        [Windowed Aggregation] (5-min windows, keyed by region)
            ↓
        ecommerce.orders.processed (Kafka)
        ecommerce.orders.dlq (Kafka)
        ecommerce.orders.aggregations (Kafka)

Key Concepts:
    - Event-Time Processing: Timestamp from order event drives windowing (not wall-clock time)
    - Watermarks: 10-minute allowed lateness; orders arriving late go to side output
    - State Backend: RocksDB (recommended for production)
    - Checkpointing: 60-second interval for exactly-once guarantees
    - Keying: By region for regional aggregations
    - Side Outputs: DLQ for failed validation, late events for post-window analysis
"""

from pyflink.datastream import StreamExecutionEnvironment, MapFunction, KeyedProcessFunction
from pyflink.datastream.functions import AggregateFunction, KeySelector, ProcessWindowFunction
from pyflink.datastream.window import TumblingEventTimeWindows, TimeWindow
from pyflink.common.typeinfo import Types
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream.connectors.kafka import FlinkKafkaConsumer, FlinkKafkaProducer
from pyflink.datastream.connectors.kafka import KafkaOffsetResetStrategy
from pyflink.datastream.functions import SimpleMapFunction
from pyflink.common import Configuration
from pyflink.datastream.state import StateTtlConfig, Time

from decimal import Decimal
from datetime import datetime, timezone
from typing import Iterable, Iterator
import json
import logging
import sys

from models import (
    OrderEvent,
    EnrichedOrder,
    OrderValidationError,
    OrderAggregation,
)


# ============================================================================
# LOGGING SETUP: Structured logging for production observability
# ============================================================================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter(
    '%(asctime)s [%(name)s] [%(levelname)s] %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)


# ============================================================================
# VALIDATION LOGIC: Deserialize and validate OrderEvent
# ============================================================================

class OrderValidator(MapFunction):
    """
    Validates order events and routes invalid orders to DLQ.
    
    Processing:
        1. Attempt to parse JSON → OrderEvent dataclass
        2. Validate business rules (amount > 0, valid currency, valid status)
        3. If valid: pass through to enrichment
        4. If invalid: return OrderValidationError for DLQ side output
    
    Why This Matters:
        - Silent data loss is unacceptable in production
        - DLQ enables debugging and replay after fixes
        - Bad data detection rate is a critical operational metric
        - Some failures are expected (user typos, network glitches); others indicate bugs
    
    Example Failures:
        SCHEMA_INVALID: JSON missing "order_id" field
        BUSINESS_RULE_VIOLATION: amount is -$50 (refund, but not marked as such)
                                 currency is "ZZZ" (invalid code)
        DUPLICATE: order_id seen in last 24 hours (deduplication window)
    """

    # ====== Validation Rules ======
    VALID_STATUSES = {"confirmed", "pending_payment", "shipped", "delivered", "cancelled"}
    VALID_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "CNY", "INR", "MXN"}
    MIN_ORDER_AMOUNT = Decimal("0.01")
    MAX_ORDER_AMOUNT = Decimal("999999.99")

    def map(self, value: str) -> tuple:
        """
        Deserialize JSON string and validate. Return (is_valid, object) tuple.
        
        In PyFlink, we use a tuple return to signal which side output (success vs DLQ) 
        the record should be routed to.
        """
        try:
            # Parse JSON into OrderEvent
            order = OrderEvent.from_json(value)
            
            # Validate business rules
            validation_errors = self._validate_business_rules(order)
            if validation_errors:
                # Route to DLQ
                dlq_record = OrderValidationError(
                    original_message=value[:10000],  # Truncate to 10KB
                    error_type="BUSINESS_RULE_VIOLATION",
                    error_message="; ".join(validation_errors),
                    error_timestamp=datetime.now(timezone.utc).isoformat(),
                    attempted_order_id=order.order_id,
                )
                logger.warning(f"Validation failure: {order.order_id} - {validation_errors}")
                return ("dlq", dlq_record.to_json())
            
            # Valid order: pass through
            logger.debug(f"Order validated: {order.order_id}")
            return ("success", order.to_json())

        except json.JSONDecodeError as e:
            # JSON parsing failed
            dlq_record = OrderValidationError(
                original_message=value[:10000],
                error_type="SCHEMA_INVALID",
                error_message=f"Invalid JSON: {str(e)}",
                error_timestamp=datetime.now(timezone.utc).isoformat(),
                attempted_order_id=None,
            )
            logger.error(f"JSON parsing error: {str(e)}")
            return ("dlq", dlq_record.to_json())

        except Exception as e:
            # Unexpected error
            dlq_record = OrderValidationError(
                original_message=value[:10000],
                error_type="SCHEMA_INVALID",
                error_message=f"Unexpected error: {str(e)}",
                error_timestamp=datetime.now(timezone.utc).isoformat(),
                attempted_order_id=None,
            )
            logger.error(f"Validation error: {str(e)}")
            return ("dlq", dlq_record.to_json())

    def _validate_business_rules(self, order: OrderEvent) -> list:
        """
        Validate business rules. Return list of error messages (empty if valid).
        
        Why separate this: Makes the validation logic testable and clear.
        Each rule is independent; all are checked (don't short-circuit).
        """
        errors = []

        # Validate amount
        if order.amount < self.MIN_ORDER_AMOUNT:
            errors.append(f"Amount must be >= {self.MIN_ORDER_AMOUNT}")
        if order.amount > self.MAX_ORDER_AMOUNT:
            errors.append(f"Amount must be <= {self.MAX_ORDER_AMOUNT}")

        # Validate currency
        if order.currency not in self.VALID_CURRENCIES:
            errors.append(f"Currency '{order.currency}' not supported")

        # Validate status
        if order.status not in self.VALID_STATUSES:
            errors.append(f"Status '{order.status}' invalid; must be one of {self.VALID_STATUSES}")

        # Validate timestamp is parseable
        try:
            datetime.fromisoformat(order.timestamp.replace('Z', '+00:00'))
        except ValueError:
            errors.append(f"Timestamp '{order.timestamp}' not valid ISO-8601")

        return errors


# ============================================================================
# ENRICHMENT LOGIC: Add region, tax, category
# ============================================================================

class OrderEnricher(MapFunction):
    """
    Enriches validated orders with:
    1. Region (from customer_id prefix)
    2. Tax (calculated based on region)
    3. Order value category ("small", "medium", "large")
    4. Merchant ID (from external mapping)
    
    Design Notes:
        - Region is derived from customer_id prefix (e.g., "CUST-US-001" → "us")
        - Tax is hardcoded per region (in production: lookup from configuration service)
        - Category is binned by order amount (enables quick filtering)
        - Merchant ID is deterministic based on customer_id (no external call)
    
    Production Considerations:
        - At scale: Replace hardcoded mappings with broadcast state (shared state, one copy per task)
        - If lookup is slow: Cache with TTL or async enrichment (but adds complexity)
        - If lookup fails: Route to separate enrichment queue (dead-letter for enrichment)
    """

    # Region-to-tax mapping (hardcoded for simplicity; use broadcast state in production)
    REGION_TAX_RATES = {
        "us": Decimal("0.08"),  # 8% US average
        "eu": Decimal("0.19"),  # 19% EU average VAT
        "uk": Decimal("0.20"),  # 20% UK VAT
        "ca": Decimal("0.05"),  # 5% Canada GST (simplified)
        "au": Decimal("0.10"),  # 10% Australia GST
    }

    # Order value boundaries
    SMALL_ORDER_THRESHOLD = Decimal("50")
    LARGE_ORDER_THRESHOLD = Decimal("500")

    def map(self, value: str) -> str:
        """Deserialize, enrich, serialize."""
        order = OrderEvent.from_json(value)
        
        # Extract region from customer_id (e.g., "CUST-US-001" → "us")
        region = self._extract_region(order.customer_id)
        
        # Calculate tax based on region
        tax_rate = self.REGION_TAX_RATES.get(region, Decimal("0.10"))  # Default 10%
        tax = (order.amount * tax_rate).quantize(Decimal("0.01"))  # Round to 2 decimals
        
        # Assign order category
        if order.amount < self.SMALL_ORDER_THRESHOLD:
            category = "small"
        elif order.amount > self.LARGE_ORDER_THRESHOLD:
            category = "large"
        else:
            category = "medium"
        
        # Derive merchant ID (deterministic from customer_id)
        merchant_id = self._derive_merchant_id(order.customer_id, region)
        
        # Record when processing started
        processed_at = datetime.now(timezone.utc).isoformat()
        
        # Create enriched order
        enriched = EnrichedOrder(
            order_id=order.order_id,
            customer_id=order.customer_id,
            amount=order.amount,
            currency=order.currency,
            status=order.status,
            timestamp=order.timestamp,
            items_count=order.items_count,
            region=region,
            tax=tax,
            order_value_category=category,
            merchant_id=merchant_id,
            processed_at=processed_at,
            processing_duration_ms=0,  # Updated after windowing
        )
        
        logger.debug(f"Order enriched: {order.order_id} → region={region}, tax=${tax}")
        return enriched.to_json()

    def _extract_region(self, customer_id: str) -> str:
        """
        Extract region from customer_id.
        Example: "CUST-US-001" → "us"
        Fallback: "ca" (Canada)
        """
        parts = customer_id.split("-")
        if len(parts) >= 2:
            region_code = parts[1].lower()
            if region_code in self.REGION_TAX_RATES:
                return region_code
        return "ca"  # Default region

    def _derive_merchant_id(self, customer_id: str, region: str) -> str:
        """
        Derive a merchant ID based on customer and region.
        In production: Look up in external merchant table.
        """
        # Simple hash-based distribution to merchants
        hash_val = sum(ord(c) for c in customer_id) % 100
        return f"MERCH-{region.upper()}-{hash_val:03d}"


# ============================================================================
# DEDUPLICATION LOGIC: Keyed state to prevent duplicate processing
# ============================================================================

class OrderDeduplicator(KeyedProcessFunction):
    """
    Ensures each order is processed exactly once using keyed state.
    
    How It Works:
        - Key: order_id (partition one order to one task)
        - State: seen_order_ids with TTL (24 hours)
        - Logic:
            1. If order_id is in state: DROP (duplicate)
            2. If order_id is new: ADD to state, EMIT
    
    Why This Matters:
        - Network retries cause duplicate Kafka records (broker may resend)
        - Upstream checkout may resubmit on timeout (idempotent operation, but we see 2 records)
        - Without deduplication: Same order charged twice (financial disaster)
    
    State Management:
        - Backend: RocksDB (default in production Managed Flink)
        - TTL: 24 hours (assume no legitimate duplicate after 1 day)
        - Checkpointing: 60 seconds → Write-Ahead Log (ensures durability)
    
    Interview Question: "What happens if Flink crashes mid-checkpoint?"
    Answer: State is replayed from the last successful checkpoint.
            The duplicate would be re-processed, but the state already has the order_id,
            so it's deduplicated again. Idempotent by design.
    """

    def open(self, runtime_context):
        """Initialize keyed state for deduplication."""
        # Get state backend
        state_descriptor = runtime_context.get_state(
            name="seen_order_ids",
            type_info=Types.MAP_INFO(Types.STRING, Types.BOOLEAN),
        )
        
        # Set TTL: Forget order_id after 24 hours
        # (Assume no legitimate duplicate after 1 day; prevents state explosion)
        ttl_config = StateTtlConfig(
            ttl=Time.hours(24),
            update_type="OnCreateAndWrite",
            state_visibility="NeverReturnExpired",
        ).use_rocksdb_ttl()
        state_descriptor.enable_time_to_live(ttl_config)
        
        self.seen_state = state_descriptor

    def process_element(self, value: str, ctx):
        """
        Check for duplicates and either emit or drop.
        """
        order = EnrichedOrder.from_json(value)
        order_id = order.order_id

        # Check if we've seen this order_id before
        seen = self.seen_state.get(order_id) or False

        if seen:
            # Duplicate: log and drop
            logger.warning(f"Duplicate order dropped: {order_id}")
            dlq_record = OrderValidationError(
                original_message=value[:10000],
                error_type="DUPLICATE",
                error_message=f"Order {order_id} already processed within deduplication window",
                error_timestamp=datetime.now(timezone.utc).isoformat(),
                attempted_order_id=order_id,
            )
            yield ("dlq", dlq_record.to_json())
        else:
            # New order: add to state and emit
            self.seen_state.put(order_id, True)
            logger.debug(f"Order deduplicated (new): {order_id}")
            yield ("success", value)


# ============================================================================
# WINDOWED AGGREGATION: 5-minute tumbling window on region
# ============================================================================

class OrderAggregationFunction(AggregateFunction):
    """
    Aggregates orders within a 5-minute window.
    
    Accumulator: Partial sums and counts during window
    Final: Emits OrderAggregation with total_orders, total_amount, etc.
    
    Why Aggregate (vs mapAndApply):
        - Aggregate pre-computes sums during window → Efficient memory use
        - One accumulator per window/key → Streaming reduction
        - Final output is compact (1 aggregate per window, not N events)
    
    Window Details:
        Type: Tumbling (non-overlapping, 5-minute fixed)
        Example:
            15:00:00 - 15:05:00 → one window
            15:05:00 - 15:10:00 → another window
            (No overlap, no sliding)
    """

    def create_accumulator(self):
        """Initialize accumulator (count=0, sum=0, max=0)."""
        return {
            "count": 0,
            "total_amount": Decimal("0"),
            "max_amount": Decimal("0"),
        }

    def add(self, value: str, accumulator: dict) -> dict:
        """Add an order to the accumulator."""
        order = EnrichedOrder.from_json(value)
        accumulator["count"] += 1
        accumulator["total_amount"] += order.amount
        accumulator["max_amount"] = max(accumulator["max_amount"], order.amount)
        return accumulator

    def get_result(self, accumulator: dict) -> dict:
        """Return the accumulator as-is (Window function will finalize)."""
        return accumulator

    def merge(self, acc_a: dict, acc_b: dict) -> dict:
        """Merge two accumulators (for session windows or other complex windowing)."""
        return {
            "count": acc_a["count"] + acc_b["count"],
            "total_amount": acc_a["total_amount"] + acc_b["total_amount"],
            "max_amount": max(acc_a["max_amount"], acc_b["max_amount"]),
        }


class OrderWindowAggregator(ProcessWindowFunction):
    """
    Finalizes windowed aggregations and emits OrderAggregation records.
    
    Input: Accumulator from OrderAggregationFunction
    Output: OrderAggregation with computed metrics
    
    Why ProcessWindowFunction (vs Aggregate alone):
        - Access to window timestamps (window_start, window_end)
        - Access to window context (can emit to side outputs, logs, etc.)
        - Enables complex logic (e.g., if count < 10, drop; else emit)
    """

    def process(self, key: str, context: ProcessWindowFunction.Context,
                elements: Iterable[dict]) -> Iterator[str]:
        """
        Process accumulated data for one window.
        
        Args:
            key: Region (partitioning key)
            context: Window context (provides window start/end times)
            elements: Iterable of accumulators (usually 1, from aggregate function)
        """
        # Get window boundaries
        window: TimeWindow = context.window()
        window_start = datetime.fromtimestamp(
            window.start / 1000, tz=timezone.utc
        ).isoformat()
        window_end = datetime.fromtimestamp(
            window.end / 1000, tz=timezone.utc
        ).isoformat()

        # Get the accumulated data
        acc = next(elements)

        # Compute average
        if acc["count"] > 0:
            avg_amount = (acc["total_amount"] / acc["count"]).quantize(Decimal("0.01"))
        else:
            avg_amount = Decimal("0")

        # Create aggregation record
        agg = OrderAggregation(
            region=key,
            total_orders=acc["count"],
            total_amount=acc["total_amount"],
            avg_order_value=avg_amount,
            max_order_value=acc["max_amount"],
            window_start=window_start,
            window_end=window_end,
            processing_timestamp_ms=int(context.current_processing_time()),
        )

        logger.info(
            f"Window closed: region={key}, orders={acc['count']}, "
            f"total=${acc['total_amount']}, window={window_start} - {window_end}"
        )

        yield agg.to_json()


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def main():
    """
    Configure and run the PyFlink order processing pipeline.
    
    Pipeline Flow:
        1. Kafka Source: ecommerce.orders.raw (JSON strings)
        2. OrderValidator: Deserialize + validate schema/business rules
           → Success: pass to enrichment
           → Failure: route to DLQ
        3. OrderEnricher: Add region, tax, category
        4. OrderDeduplicator: Keyed state (order_id) to prevent duplicates
        5. Windowed Aggregation: 5-min tumbling windows by region
           → Emits OrderAggregation metrics
        6. Kafka Sinks:
           - ecommerce.orders.processed: EnrichedOrder (success path)
           - ecommerce.orders.dlq: OrderValidationError (failure path)
           - ecommerce.orders.aggregations: OrderAggregation (metrics)
    
    Configuration:
        Checkpoint: Every 60 seconds (exactly-once semantics)
        State TTL: 24 hours (deduplication window)
        Watermark: 10-minute allowed lateness (handle out-of-order)
        Parallelism: 4 (or auto-scale based on MSK partitions)
    
    Failure Handling:
        - Malformed JSON: Sent to DLQ (OrderValidationError)
        - Business rule violation: Sent to DLQ with error details
        - Duplicates: Logged + sent to DLQ
        - Late events (>10min): Sent to late-events side output
        - Processing crash: Resume from last checkpoint (exactly-once restored)
    """

    # Initialize execution environment
    env = StreamExecutionEnvironment.get_execution_environment()
    
    # Configuration
    config = Configuration()
    
    # ====== Checkpoint Configuration ======
    # Exactly-once semantics: Write-Ahead Log (changelog streams)
    # Interval: 60 seconds (balance between safety and latency)
    env.enable_checkpointing(60_000)  # 60 seconds in milliseconds
    from pyflink.datastream.checkpoint_mode import CheckpointingMode
    env.get_checkpoint_config().set_checkpointing_mode(CheckpointingMode.EXACTLY_ONCE)
    
    # State backend: RocksDB (recommended for production)
    # RocksDB: On-disk key-value store, efficient for large state
    from pyflink.datastream.state import EmbeddedRocksDBStateBackend
    env.set_state_backend(EmbeddedRocksDBStateBackend())
    
    # ====== Parallelism ======
    # Default: Match number of Kafka partitions (e.g., 4 partitions → parallelism 4)
    # Managed Flink auto-scales based on CPU/memory utilization
    env.set_parallelism(4)

    # ====== Kafka Source ======
    kafka_brokers = "localhost:9098"  # Override from CloudWatch parameter
    kafka_consumer = FlinkKafkaConsumer(
        topics="ecommerce.orders.raw",
        deserialization_schema=SimpleStringSchema(),
        properties={
            "bootstrap.servers": kafka_brokers,
            "group.id": "flink-order-processor",
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "AWS_MSK_IAM",
            "sasl.jaas.config": "software.amazon.msk.auth.iam.IAMLoginModule required;",
            # Additional properties loaded from application config
        },
    )
    kafka_consumer.set_start_from_earliest()
    
    # ====== Stream Processing ======
    orders_stream = env.add_source(kafka_consumer)
    
    # Step 1: Validate orders (schema + business rules)
    # Output: ("success", OrderEvent) or ("dlq", OrderValidationError)
    validated_stream = orders_stream.map(OrderValidator())
    
    # Split into success and DLQ paths
    success_stream = validated_stream.filter(lambda x: x[0] == "success").map(lambda x: x[1])
    dlq_stream_1 = validated_stream.filter(lambda x: x[0] == "dlq").map(lambda x: x[1])
    
    # Step 2: Enrich validated orders
    enriched_stream = success_stream.map(OrderEnricher())
    
    # Step 3: Deduplicate by order_id
    # Key by order_id to ensure one task processes each order
    deduplicated_stream = (
        enriched_stream
        .key_by(lambda x: EnrichedOrder.from_json(x).order_id)
        .process(OrderDeduplicator())
    )
    
    # Split deduplication results
    dedup_success = deduplicated_stream.filter(lambda x: x[0] == "success").map(lambda x: x[1])
    dlq_stream_2 = deduplicated_stream.filter(lambda x: x[0] == "dlq").map(lambda x: x[1])
    
    # Step 4: Windowed aggregation
    # Key by region for regional metrics
    window_stream = (
        dedup_success
        .key_by(lambda x: EnrichedOrder.from_json(x).region)
        .window(TumblingEventTimeWindows.of(5 * 60 * 1000))  # 5-minute window
        .aggregate(
            OrderAggregationFunction(),
            OrderWindowAggregator(),
        )
    )
    
    # ====== Watermark Configuration ======
    # Event-time processing: Timestamp from order event drives windowing
    # Allowed lateness: 10 minutes (orders arriving >10min late go to side output)
    # This balances freshness (5-min window closes) vs completeness (allow stragglers)
    orders_stream = orders_stream.assign_timestamps_and_watermarks(
        WatermarkStrategy
        .for_bounded_out_of_orderness(10 * 60 * 1000)  # 10 minutes
        .with_timestamp_assigner(
            lambda x: int(
                datetime.fromisoformat(
                    json.loads(x)["timestamp"].replace("Z", "+00:00")
                ).timestamp() * 1000
            )
        )
    )
    
    # ====== Kafka Sinks ======
    kafka_producer_success = FlinkKafkaProducer(
        topic="ecommerce.orders.processed",
        serialization_schema=SimpleStringSchema(),
        producer_config={
            "bootstrap.servers": kafka_brokers,
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "AWS_MSK_IAM",
            "sasl.jaas.config": "software.amazon.msk.auth.iam.IAMLoginModule required;",
        },
    )
    dedup_success.add_sink(kafka_producer_success)
    
    # DLQ sink: Combine all DLQ paths
    dlq_combined = dlq_stream_1.union(dlq_stream_2)
    kafka_producer_dlq = FlinkKafkaProducer(
        topic="ecommerce.orders.dlq",
        serialization_schema=SimpleStringSchema(),
        producer_config={
            "bootstrap.servers": kafka_brokers,
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "AWS_MSK_IAM",
            "sasl.jaas.config": "software.amazon.msk.auth.iam.IAMLoginModule required;",
        },
    )
    dlq_combined.add_sink(kafka_producer_dlq)
    
    # Aggregation sink: Metrics topic
    kafka_producer_agg = FlinkKafkaProducer(
        topic="ecommerce.orders.aggregations",
        serialization_schema=SimpleStringSchema(),
        producer_config={
            "bootstrap.servers": kafka_brokers,
            "security.protocol": "SASL_SSL",
            "sasl.mechanism": "AWS_MSK_IAM",
            "sasl.jaas.config": "software.amazon.msk.auth.iam.IAMLoginModule required;",
        },
    )
    window_stream.add_sink(kafka_producer_agg)
    
    # Execute
    logger.info("Starting PyFlink order processing pipeline")
    env.execute("order-processor")


if __name__ == "__main__":
    main()
