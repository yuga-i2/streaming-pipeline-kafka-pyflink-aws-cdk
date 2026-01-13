# Failure Modes & Detection Strategy
## PyFlink Streaming Platform Observability

---

## Critical Failure Modes (in order of severity)

### CATEGORY 1: DATA LOSS (Most Severe)
**Impact**: Orders never reach S3, revenue can't be reconciled

| Mode | Current Detection | Proposed Detection |
|------|-------------------|-------------------|
| **DLQ Spike (Parse/Processing Error)** | Manual log review | Metric: `dlq_records_total` (alarm at >100/min) + CloudWatch Logs Insights query |
| **Checkpoint Failure** | Flink logs (buried) | Metric: `checkpoint_duration_ms`, `checkpoint_failures_total` with alarms |
| **Window State Loss** | Hours later when metrics don't match | Metric: `window_completeness` (records in vs. records out per window) + real-time alert |
| **Kafka Rebalancing (Silent Data Discard)** | Not detected | Metric: `consumer_lag`, `rebalance_duration`, `rebalance_count` |
| **S3 Upload Failure** | Firehose CloudWatch logs | Metric: `firehose_failed_put_count` + alarm on delivery status |
| **Duplicate Detection Failure** | Discovered during reconciliation | Metric: `duplicate_records_total` (counter in DLQ processor) |

**SLA**: Zero data loss (backfill from Kafka if S3 failure detected)

---

### CATEGORY 2: LATENCY (Customer Impact)
**Impact**: Real-time dashboards lag, customer features stale

| Mode | Current Detection | Proposed Detection |
|------|-------------------|-------------------|
| **End-to-End Latency Spike** | Manual query of timestamps | Metric: `processing_latency_p50/p95/p99` (timestamp difference) + alarm at p99 > 5s |
| **Kafka Lag Building** | Manual `kafka-consumer-groups` | Metric: `consumer_lag_records` per partition + alarm at lag > 10k records |
| **Checkpoint Long** | Flink taskmanager logs | Metric: `checkpoint_duration_ms` + alarm at > 30s (indicates backpressure) |
| **Backpressure (Operator Queued)** | Flink UI (not accessible to ops) | Metric: `task_buffer_out_pool_usage_percentage` + alarm at > 80% |
| **Window Emitting Slow** | No detection | Metric: `window_emit_latency_ms` + alarm at p99 > 2s |

**SLA**: p99 latency < 5 seconds, p95 < 2 seconds

---

### CATEGORY 3: CORRECTNESS (Revenue Impact)
**Impact**: Wrong order counts, duplicate aggregations, incorrect totals

| Mode | Current Detection | Proposed Detection |
|------|-------------------|-------------------|
| **Window Completeness** | End-of-day reconciliation (hours late) | Metric: `window_completeness_percentage` = (records emitted / records in) * 100, alarm < 95% |
| **Late Arrivals Not Captured** | Query S3 vs. Kafka | Metric: `late_arrival_records_total` (counter in allowed lateness processing) |
| **State Corruption** | Not detected until customers report | Metric: `state_backend_used_bytes`, `state_read_count`, `state_write_count` + sanity checks |
| **Watermark Stuck** | Not detected | Metric: `watermark_lag_ms` (current_time - watermark) + alarm at > 60s |
| **Duplicate Records** | Database deduplication | Metric: `duplicate_records_total` + alarm at > 10 per window |

**SLA**: 100% correctness (no duplicates, no missing records within allowed lateness)

---

### CATEGORY 4: RESOURCE EXHAUSTION (Availability)
**Impact**: Flink task manager crashes, pipeline stalls

| Mode | Current Detection | Proposed Detection |
|------|-------------------|-------------------|
| **Memory Leak** | Task manager OOMKilled | Metric: `memory_usage_percentage` + alarm at > 85%, trend analysis over 1 hour |
| **CPU Saturation** | Task manager CPU throttle | Metric: `cpu_usage_percentage` + alarm at > 90%, check against throughput (is it justified?) |
| **Network Saturation** | Lag increases mysteriously | Metric: `network_in_bytes_per_second`, `network_out_bytes_per_second` + alarm at > 80% of NIC capacity |
| **Disk State Backend Full** | Task manager crashes | Metric: `state_backend_disk_free_bytes` + alarm at < 20% free space |
| **Thread Pool Exhaustion** | Flink logs, hard to find | Metric: `thread_pool_active_threads`, `thread_pool_queue_size` + alarm at queue > 100 |

**SLA**: 99.9% availability (< 8 hours downtime per month)

---

### CATEGORY 5: INFRASTRUCTURE (Operational)
**Impact**: Silent failures, deployment issues, configuration drift

| Mode | Current Detection | Proposed Detection |
|------|-------------------|-------------------|
| **Kafka Broker Down** | Producer sees exception | Metric: `kafka_broker_alive_count` (via broker metrics export) + alarm at < 3 brokers |
| **Flink Replica Unstable** | Fluctuating task manager count | Metric: `task_manager_count`, `task_manager_startup_failures` + alarm at variance > 2 |
| **Firehose Quota Exceeded** | Silent rate limiting | Metric: `firehose_throttle_count` + alarm at > 0 |
| **CloudWatch API Rate Limited** | Metrics not flowing | Metric: `cloudwatch_putmetric_errors` (from Flink custom metrics) + alarm at > 0 |
| **Configuration Drift** | Manual verification | Metric: `config_version` (hash of config file) + alarm on change |

**SLA**: 99.5% infrastructure availability

---

## Observable Signals (What We Can See)

### Tier 1: Always-On Metrics (1-second granularity)
These must always flow, otherwise observability is blind:

```
Kafka:
├── consumer_lag_records (per partition)
├── consumer_position_offset (per partition)
├── kafka_message_in_per_second (throughput)
└── kafka_deserialization_errors_total

Flink:
├── records_in_total (per operator)
├── records_out_total (per operator)
├── checkpoint_duration_ms (every checkpoint)
├── checkpoint_failures_total
├── task_manager_heap_used_bytes
├── task_manager_gc_time_ms
└── thread_pool_queue_size

Firehose:
├── firehose_failed_put_count (every second)
├── firehose_throttle_count
└── s3_bucket_size_bytes (once per minute)

Application:
├── processing_latency_ms (p50, p95, p99, per window)
├── dlq_records_total (cumulative counter)
├── window_completeness_percentage
├── duplicate_records_total
└── watermark_lag_ms
```

### Tier 2: Health Metrics (10-second granularity)
Useful for diagnosing but not critical if delayed:

```
Flink:
├── buffer_out_pool_usage_percentage
├── memory_usage_percentage
├── cpu_usage_percentage
└── network_throughput_bytes_per_second

Infrastructure:
├── task_manager_count
├── task_manager_health_status
├── kafka_broker_count
└── firehose_delivery_stream_state
```

### Tier 3: Deep Debugging Metrics (1-minute granularity)
Used for RCA when something is wrong:

```
Flink State:
├── state_backend_used_bytes
├── state_read_count
├── state_write_count
└── state_access_latency_ms

Checkpointing:
├── checkpoint_size_bytes
├── checkpoint_aligned_vs_unaligned_ratio
└── checkpoint_trigger_source

JVM:
├── gc_pause_time_ms (p99)
├── gc_pause_count_per_minute
└── gc_memory_freed_bytes
```

---

## Detection Strategy by Failure Mode

### For Data Loss: Defense in Depth

**Tier 1: Real-Time Detection**
- DLQ metric alert (>100 records/min) → Page on-call
- Checkpoint failure counter (>0 in 5 min) → Page immediately
- Kafka lag metric (>50k records) → Alert to slack (investigate within 1 hour)

**Tier 2: Periodic Checks**
- Window completeness query (every 5 min) → If <95%, investigate
- Late arrival count (every min) → If spike, check watermark

**Tier 3: Reconciliation**
- Hourly: Compare Kafka record count vs. S3 record count
- Daily: Compare order totals vs. database

### For Latency: SLO Tracking

```
p99 latency metric → SLO 5 seconds
├── At 3 seconds: Yellow alert (investigate)
├── At 5 seconds: Orange alert (auto-scale trigger)
└── At 8 seconds: Red alert (page on-call)

Kafka lag metric → SLO < 10k records
├── At 5k: Yellow (monitor)
├── At 10k: Orange (check consumer performance)
└── At 20k: Red (page)
```

### For Correctness: Invariant Checks

```
Every 5 minutes:
1. ∑(records_in) >= ∑(records_out)  [Nothing created from nowhere]
2. ∑(records_out) = ∑(records_in - dlq - lost_to_rebalance)  [Conservation of records]
3. Dedup filter rate < 1%  [If >1%, investigate source]
4. Watermark lag < 60 seconds  [Processing is timely]
```

---

## Dashboard Layout (What We'll Monitor)

### Page 1: "Is the Pipeline Working?" (Health)
- **Kafka Lag** (single number, red/yellow/green)
- **Checkpoint Success Rate** (%)
- **DLQ Rate** (records/sec)
- **Processing Latency p99** (ms)
- **Window Completeness** (%)

### Page 2: "Where's the Bottleneck?" (Performance)
- Throughput in vs. out (stacked bars)
- Checkpoint duration (trend)
- Buffer usage (%)
- Memory usage (%)
- Backpressure indicators (operator queue depth)

### Page 3: "What's Broken?" (Error Details)
- DLQ breakdown by error type (pie chart)
- Checkpoint failures by reason (bar chart)
- Firehose delivery status (success/failure counts)
- S3 upload errors (count over time)

### Page 4: "Can We Handle More?" (Capacity)
- CPU, Memory, Network utilization
- Kafka brokers alive
- Flink task managers alive
- State backend storage used
- Firehose throttles

---

## Alert Thresholds (SLO-Based)

| Metric | Threshold | Severity | Action |
|--------|-----------|----------|--------|
| `dlq_records_total` rate | >100/min | CRITICAL | Page immediately |
| `checkpoint_failures_total` | >0 in 5 min | CRITICAL | Investigate state |
| `consumer_lag_records` | >50k | HIGH | Scale up / investigate |
| `processing_latency_p99` | >5s | HIGH | Check backpressure |
| `window_completeness` | <95% | HIGH | Check late arrivals |
| `memory_usage` | >85% | MEDIUM | Monitor for leak |
| `kafka_broker_count` | <3 | CRITICAL | Page ops |
| `task_manager_count` | <2 | CRITICAL | Page ops |
| `firehose_failed_put_count` | >0 in 1 min | HIGH | Investigate S3 permissions |
| `duplicate_records_total` rate | >10/window | MEDIUM | Investigate source |

---

## Why This Matters (Interview Answers)

### "How do you detect data loss?"

**Current (Bad)**: Manual log review, days late

**Proposed**:
1. Real-time DLQ counter → immediately visible
2. Kafka lag metric → shows if falling behind
3. Checkpoint failure → shows if state is lost
4. Hourly reconciliation → numbers must match Kafka
5. CloudTrail audit → proves data made it to S3

Together: Can detect data loss within **minutes** instead of **days**, with **proof** of where it went.

---

### "How do you know Flink is healthy?"

**One-Sentence Answer**: "Dashboard shows 5 golden signals: lag trending down, DLQ rate < 100/min, checkpoints succeeding, latency p99 < 5s, window completeness > 95%."

**Details**:
- Lag trending down = keeping up with producer
- DLQ low = records are parseable
- Checkpoints = state is being saved
- Latency SLO met = customers get fresh data
- Window completeness = no silent data loss

If any of these are red, we page someone immediately.

---

### "How would you debug a DLQ spike?"

**Process** (using metrics + logs):

1. **Detect** (metric alert): `dlq_records_total` rate > 100/min
2. **Classify** (structured logs): Query CloudWatch Logs
   ```
   fields @timestamp, order_id, error_type, error_message
   filter dlq = true
   stats count() by error_type
   ```
3. **Drill down** (per-error dashboards):
   - Parse error? → Check source data schema
   - Duplicate? → Check dedup window
   - Timeout? → Check external API latency
4. **Fix**: Change code or config
5. **Verify**: Watch DLQ rate drop in real-time on dashboard

Time to fix: **5-10 minutes** (instead of hours).

---

## Metrics Retention & Aggregation

| Metric Type | Raw Granularity | Retention | Aggregation |
|-------------|---|---|---|
| Throughput (records/sec) | 1 sec | 30 days | Average per minute after day 1 |
| Latency (ms) | per record | 1 day | Percentiles (p50, p95, p99) kept 30 days |
| Errors (count) | 1 sec | 30 days | Cumulative counter |
| Resource (%, bytes) | 10 sec | 7 days | Average per minute |
| Checkpoints | per event | 30 days | Raw (not aggregated) |

**Rationale**: Keep high-resolution data for active incidents (1-7 days), aggregate for trend analysis (30 days), drop after 30 days (cost).

---

## Next: Implement This Detection

**Code to write**:
1. Custom metrics classes (PyFlink)
2. Structured logging patterns
3. CloudWatch Logs Insights queries
4. Alert rule definitions
5. Dashboard JSON templates

**Interview value**: You've gone from "we don't know if it's working" to "we can detect any failure within minutes and know exactly what broke."

