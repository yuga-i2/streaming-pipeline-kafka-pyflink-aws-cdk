# PyFlink Order Processing Application

Real-time e-commerce order processing with validation, enrichment, and windowed aggregation.

## Architecture

```
ecommerce.orders.raw (Kafka)
        ↓
   [OrderValidator]
   ├─→ Valid orders
   │     ↓
   │  [OrderEnricher]
   │     ↓
   │  [OrderDeduplicator]
   │     ↓
   │  [Windowed Aggregation]
   │     ├─→ ecommerce.orders.processed (EnrichedOrder)
   │     └─→ ecommerce.orders.aggregations (OrderAggregation)
   │
   └─→ Invalid orders → ecommerce.orders.dlq (OrderValidationError)
```

## Key Features

### 1. **Event-Time Processing**
- Timestamps from order events drive windowing (not wall-clock time)
- Handles out-of-order arrivals gracefully
- Watermarks: 10-minute allowed lateness

### 2. **Exactly-Once Semantics**
- 60-second checkpointing (Write-Ahead Log)
- RocksDB state backend (durable, efficient)
- Deduplication via keyed state (order_id)

### 3. **Validation & Error Handling**
- Schema validation (JSON parsing, required fields)
- Business rule validation (amount > 0, valid currency, valid status)
- DLQ pattern: Failed records routed to separate topic with error details

### 4. **Enrichment**
- Region extraction from customer_id
- Tax calculation per region
- Order value categorization (small/medium/large)
- Merchant assignment

### 5. **Windowed Aggregation**
- 5-minute tumbling windows (non-overlapping)
- Keyed by region for regional metrics
- Computes: count, total_amount, avg_order_value, max_order_value

## File Structure

```
flink_pyflink_app/
├── __init__.py              # Package initialization
├── models.py                # Data schemas (OrderEvent, EnrichedOrder, etc.)
├── order_processor.py       # Main Flink job (validation, enrichment, windowing)
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## Data Models

### OrderEvent (Input)
```python
{
    "order_id": "ORD-20250113-001234",
    "customer_id": "CUST-US-001",
    "amount": "149.99",
    "currency": "USD",
    "status": "confirmed",
    "timestamp": "2025-01-13T15:30:45.123Z",
    "items_count": 3
}
```

### EnrichedOrder (Output)
```python
{
    "order_id": "ORD-20250113-001234",
    "customer_id": "CUST-US-001",
    "amount": "149.99",
    "currency": "USD",
    "status": "confirmed",
    "timestamp": "2025-01-13T15:30:45.123Z",
    "items_count": 3,
    "region": "us",
    "tax": "12.00",
    "order_value_category": "medium",
    "merchant_id": "MERCH-US-042",
    "processed_at": "2025-01-13T15:30:46.234Z",
    "processing_duration_ms": 1091
}
```

### OrderValidationError (DLQ)
```python
{
    "original_message": "{...malformed JSON...}",
    "error_type": "BUSINESS_RULE_VIOLATION",
    "error_message": "Amount must be > 0",
    "error_timestamp": "2025-01-13T15:30:46.234Z",
    "attempted_order_id": "ORD-20250113-001234"
}
```

### OrderAggregation (Metrics)
```python
{
    "region": "us",
    "total_orders": 42,
    "total_amount": "6324.58",
    "avg_order_value": "150.58",
    "max_order_value": "499.99",
    "window_start": "2025-01-13T15:25:00Z",
    "window_end": "2025-01-13T15:30:00Z",
    "processing_timestamp_ms": 1673612400123
}
```

## Running Locally

### Prerequisites
```bash
pip install -r requirements.txt
```

### Start Kafka (Docker Compose)
```bash
docker-compose up -d
```

### Run the Flink Job
```bash
python -m flink_pyflink_app.order_processor
```

### Send Test Events
```bash
python send_test_orders.py
```

### Monitor Output
```bash
# Subscribe to processed orders
kafka-console-consumer --bootstrap-server localhost:9098 \
  --topic ecommerce.orders.processed \
  --from-beginning

# Monitor DLQ
kafka-console-consumer --bootstrap-server localhost:9098 \
  --topic ecommerce.orders.dlq \
  --from-beginning

# Monitor aggregations
kafka-console-consumer --bootstrap-server localhost:9098 \
  --topic ecommerce.orders.aggregations \
  --from-beginning
```

## Configuration

### Flink Runtime Properties
Configured in `order_processor.py`:
- **Checkpointing**: Every 60 seconds (exactly-once)
- **State Backend**: RocksDB (production-grade)
- **Parallelism**: 4 (match Kafka partitions)
- **Watermark**: 10-minute allowed lateness

### Kafka Connection
In production (Managed Flink), properties are overridden by CloudWatch Application Config:
```json
{
  "FlinkApplicationProperties": {
    "bootstrap.servers": "broker1:9098,broker2:9098,broker3:9098",
    "input.topic": "ecommerce.orders.raw",
    "output.topic": "ecommerce.orders.processed",
    "dlq.topic": "ecommerce.orders.dlq",
    "metrics.topic": "ecommerce.orders.aggregations"
  }
}
```

## Validation Rules

### Schema Validation
- All required fields present: order_id, customer_id, amount, currency, status, timestamp, items_count
- Data types correct: amount is numeric, timestamp is ISO-8601

### Business Rule Validation
- **Amount**: Must be between $0.01 and $999,999.99
- **Currency**: Must be valid ISO 4217 code (USD, EUR, GBP, JPY, etc.)
- **Status**: Must be one of: confirmed, pending_payment, shipped, delivered, cancelled
- **Timestamp**: Must be valid ISO-8601 format

Failures → OrderValidationError (DLQ)

## Enrichment Logic

### Region Extraction
- From customer_id prefix (e.g., "CUST-**US**-001" → "us")
- Fallback: "ca" (Canada) if prefix not recognized

### Tax Calculation
- Region-specific rates (hardcoded; use broadcast state in production):
  - US: 8%, EU: 19%, UK: 20%, CA: 5%, AU: 10%
- Formula: `tax = amount * region_tax_rate` (rounded to 2 decimals)

### Order Value Category
- **small**: amount < $50
- **medium**: $50 ≤ amount ≤ $500
- **large**: amount > $500

Use cases: Quick filtering for business intelligence, anomaly detection

### Merchant ID Derivation
- Hash-based distribution: `sum(ord(c) for c in customer_id) % 100`
- Format: `MERCH-{REGION}-{HASH:03d}`
- Deterministic: Same customer always maps to same merchant (for transaction settlement)

## Deduplication

### How It Works
- **Key**: order_id (ensures one task processes each order)
- **State**: Boolean flag (order_id → true/false)
- **TTL**: 24 hours (assume no legitimate duplicate after 1 day)
- **Logic**:
  1. If order_id already in state: DROP + send to DLQ
  2. If order_id new: ADD to state + EMIT

### Why Necessary
- Network retries cause Kafka brokers to resend messages
- Upstream checkout may resubmit on timeout
- Without deduplication: Same order charged twice (financial disaster)

## Windowed Aggregation

### Windowing Strategy
- **Type**: Tumbling (non-overlapping, 5-minute fixed windows)
- **Timing**: 5-minute windows on event-time (not wall-clock time)
- **Example**:
  - Window 1: 15:00:00 - 15:05:00
  - Window 2: 15:05:00 - 15:10:00
  - (No overlap, no sliding)

### Key
- **region**: All orders from us-west-2 go to one aggregation, eu-central-1 to another

### Aggregations
- **total_orders**: Count of orders in window
- **total_amount**: Sum of all order amounts
- **avg_order_value**: `total_amount / total_orders`
- **max_order_value**: Maximum single order amount

### Use Cases
1. **Monitoring**: Detect regional outages (sudden drop in order count)
2. **Alerting**: Spike detection (5x normal volume = possible attack)
3. **Billing**: Reconciliation counts
4. **Analytics**: Input to ML anomaly detection models

## Handling Late Events

### Watermark Strategy
- **Bounded Out-of-Orderness**: 10-minute allowed lateness
- **Window Closure**: After watermark passes window end + 10 minutes
- **Late Events**: Orders arriving >10 minutes late are sent to side output

### Example
- Order event timestamp: 15:20:00
- Window: 15:20:00 - 15:25:00
- Watermark at: 15:35:05 (no more events before 15:25:05 expected)
- Order arrives at: 15:36:00 (16 minutes late)
- Result: Order sent to late-events side output (not included in window)

### Trade-Off
- **Freshness**: Windows close after 5 minutes (near real-time)
- **Completeness**: Allow 10 minutes for stragglers (missing <1% of orders)
- **Memory**: Increased state size (keeping windows open longer)

## Interview Preparation

### Question: "Why PyFlink instead of Java?"

**Answer**: 
> We chose PyFlink for development velocity without sacrificing production guarantees. PyFlink 1.20 has feature parity with Java Flink (exactly-once semantics, event-time windowing, state management), and we gain:
> 
> 1. **Faster iteration**: No Maven compilation cycle; Python is interpreted
> 2. **Team productivity**: Our team knows Python; zero ramp-up for Flink concepts
> 3. **AWS integration**: Managed Flink has native PyFlink support (1.20+)
> 4. **Ecosystem**: Access to Python ML libraries (NumPy, scikit-learn) for enrichment
> 
> Trade-offs: IDE debugging is harder (print logging vs breakpoints), and JVM optimizations are lost. But at <5K orders/sec, Python performance is adequate.

### Question: "What happens if Flink crashes mid-checkpoint?"

**Answer**:
> State is recovered from the last successful checkpoint. Here's the flow:
> 
> 1. Flink takes a checkpoint every 60 seconds (synchronous)
> 2. All state (deduplication, aggregations) is written to S3 + RocksDB changelog
> 3. If job crashes at second 35 of a checkpoint:
>    - Last successful checkpoint is at second 0 (60 seconds ago)
>    - Job restarts and reloads state from second 0
>    - Kafka offsets are also checkpointed, so no records are re-processed
> 4. The 35 seconds of processing is lost, and events are replayed from Kafka
>
> Result: Exactly-once semantics maintained. No data loss, no duplicates.

### Question: "How do you handle state explosion at scale?"

**Answer**:
> As order volume grows, deduplication state could explode (every order_id stored forever).
> 
> Mitigations:
> 1. **TTL Policy**: 24-hour state TTL (assume no duplicate after 1 day) → automatic cleanup
> 2. **Parallelism**: Distribute deduplication across 16 tasks (16x parallelism) → state per task is smaller
> 3. **RocksDB Compression**: Compress state at rest (4:1 typical compression ratio)
> 4. **Monitoring**: CloudWatch metrics on state size; alert if >5GB per task
> 5. **If needed**: Switch from deduplication to UUID-based idempotency keys (idempotent sink)
>
> At 100K orders/sec with 24-hour TTL: ~8.6 billion order_ids, ~170GB total state.
> Distributed across 16 tasks: ~11GB per task (RocksDB can handle this).

### Question: "How would you migrate back to Java if needed?"

**Answer**:
> Low friction, because we separated concerns:
> 
> 1. **Data Models**: OrderEvent, EnrichedOrder are pure dataclasses (no Flink code)
>    → Reimplementing as Java POJOs takes 1 day
> 2. **Processing Logic**: Validation, enrichment, aggregation are stateless functions
>    → Translating to Java Flink operators is straightforward (no architectural changes)
> 3. **CDK Stack**: Infrastructure code (IAM, networking) is language-agnostic
>    → Only update entrypoint reference and Flink version
> 4. **Testing**: Re-run golden tests on Java implementation for feature parity
>
> Timeline: 2-3 weeks for experienced Java/Flink engineer.

## Troubleshooting

### No Data in Output Topics
- Check Kafka broker connectivity: `kafka-broker-api-versions --bootstrap-server localhost:9098`
- Check input topic has data: `kafka-console-consumer --topic ecommerce.orders.raw --from-beginning`
- Check Flink logs: `tail -f /tmp/flink*.log`

### High DLQ Rate
- Sample DLQ messages: `kafka-console-consumer --topic ecommerce.orders.dlq | head -20`
- Check error_type and error_message fields
- Verify upstream schema (checkout system may have changed)

### State Size Growing
- Monitor RocksDB size: `du -sh /tmp/flink-state/`
- Check TTL policy is working: Verify old order_ids are removed after 24h
- Increase parallelism to distribute state across more tasks

### Latency High
- Check window closure time in logs: Should be 5 minutes after event timestamp
- Monitor watermark progress: `kafka-console-consumer --topic ecommerce.orders.aggregations | jq .processing_timestamp_ms`
- Check Kafka consumer lag: May be backed up on input topic

## Production Deployment

See `../streaming_pipeline_kafka_flink_firehose_s3_cdk/order_processing_stack.py` for CDK-based deployment to AWS Managed Flink.

Key differences:
- Python script uploaded to S3 as deployment artifact
- Managed Flink handles scaling, networking, logging
- CloudWatch Parameter Store provides runtime configuration
- Auto-scaling based on CPU/memory utilization

---

**Prepared by**: Data Engineering Team  
**Last Updated**: January 2026  
**Status**: Production-Ready
