# OBSERVABILITY_GUIDE.md
## Complete SRE Observability Strategy for PyFlink Streaming Pipeline

---

## Executive Summary

This guide defines production-grade observability for a real-time streaming platform processing 100K+ orders/day. It covers:

- **Metrics**: What to measure (throughput, latency, errors, resources)
- **Logging**: How to trace issues (structured JSON, correlation IDs)
- **Alerting**: When to page (critical thresholds, SLOs)
- **Dashboards**: How to visualize (health, performance, errors, capacity)
- **Interview Talking Points**: How to explain observability strategy

---

## Section 1: Failure Mode Detection

### Data Loss Detection

**Scenario**: Records don't make it from Kafka to S3

**Detection Strategy** (Defense in Depth):

1. **Real-Time Metric**: DLQ counter
   - Metric: `DLQRecordCount` rate
   - Alert: >100/min = page immediately
   - Why: 100/min = 6K/hour = systematic issue

2. **Real-Time Metric**: Checkpoint failures
   - Metric: `checkpoint_failures_total`
   - Alert: >0 in 5 min = page immediately
   - Why: Can't save state = restart loses records

3. **Periodic Check**: Kafka lag metric
   - Metric: `consumer_lag_records`
   - Alert: >50K = investigate (might lose data if lag keeps growing)
   - Why: Falling behind = will eventually overflow

4. **Hourly Reconciliation**: Compare Kafka vs. S3 record counts
   - Count records in Kafka topic (last 24 hours)
   - Count records in S3 (last 24 hours)
   - Should match (within DLQ percentage)
   - Script: See `scripts/reconciliation_check.sh`

5. **Daily Manual Review**: Check S3 records by day
   - Verify order counts match order database
   - Verify no gaps in hourly data
   - Alert if <99.9% match

**Interview Answer**: "We detect data loss through 5 layers: real-time DLQ metrics, checkpoint success tracking, consumer lag monitoring, hourly reconciliation counts, and daily database validation. Any of these triggers investigation within minutes."

---

### Latency Detection

**Scenario**: Real-time features break because data is stale

**Detection Strategy**:

1. **Real-Time Metric**: Processing latency percentiles
   - Metrics: `LatencyP50`, `LatencyP95`, `LatencyP99` (every 60 sec)
   - Alert: P99 > 5 seconds = SLO breach
   - Why: Customers need data within 5 sec for real-time features

2. **SLO Tracking**: Dashboard with trend
   - Visual: Green (normal), Yellow (warning), Red (breach)
   - Helps on-call recognize issue immediately

3. **Per-Operator Analysis**: Which operator is slow?
   - Metrics per operator: avg latency, max latency
   - Query: `fields operator, latency_ms | stats avg(latency_ms) by operator`
   - Helps drill down to root cause (enrichment? windowing? Firehose?)

4. **Root Cause Correlation**:
   - If latency spikes = check CPU usage
   - If CPU high = check enrichment API latency
   - If enrichment slow = check cache hit rate
   - Enables quick diagnosis

**Interview Answer**: "We track latency at 3 levels: aggregate (p50/p95/p99), per-operator, and per-component (cache hit rate, API latency). This lets us detect latency within 60 seconds and identify the bottleneck within 2 minutes."

---

### Correctness Detection

**Scenario**: Duplicate records or silent data loss in aggregations

**Detection Strategy**:

1. **Window Completeness Metric**
   - Metric: `WindowCompleteness` = (records out / records in) * 100
   - Alert: <95% = potential data loss
   - Granularity: Per window (5 min)
   - Why: Shows if records are being dropped silently

2. **Duplicate Detection Counter**
   - Metric: `DuplicateRecordDetected` rate
   - Normal: <1/min
   - Alert: >10/min = systematic duplicate source
   - Why: If dedup isn't working, duplicates will pass through

3. **Invariant Checks** (queries, not metrics)
   ```sql
   -- Every 5 minutes:
   -- Check: Total output >= Total input - DLQ - Late arrivals
   output = (input - dlq - late_arrivals)
   
   -- Check: No duplicates in final S3 output
   SELECT COUNT(DISTINCT order_id) as unique_orders,
          COUNT(*) as total_orders
   FROM s3_data
   WHERE date = TODAY
   -- Should match
   
   -- Check: Watermark lag < 60 seconds
   -- (Events being processed in real-time, not delayed)
   ```

4. **Sample Validation** (hourly)
   - Pick 100 random order_ids from S3
   - Verify they match order database
   - Verify no duplicates
   - Verify all required fields present

**Interview Answer**: "We ensure correctness through window completeness monitoring, duplicate rate tracking, and hourly invariant validation. Any data that violates our integrity constraints triggers immediate investigation and potential backfill."

---

## Section 2: Metrics Catalog

### Tier 1: Always-On Metrics (1-second granularity, 30-day retention)

**Kafka Source**:
- `consumer_lag_records` (per partition): How far behind producer
- `consumer_position_offset` (per partition): Current position
- `kafka_message_in_per_second`: Throughput from source
- `kafka_deserialization_errors_total`: Unparseable messages

**PyFlink Processing**:
- `RecordsIn` (per operator): Records entering operator
- `RecordsOut` (per operator): Records exiting operator
- `RecordsError` (per operator): Records that failed
- `checkpoint_duration_ms`: How long checkpoint takes
- `checkpoint_failures_total`: Number of failed checkpoints

**Firehose Delivery**:
- `firehose_failed_put_count`: Delivery failures to S3
- `firehose_throttle_count`: Rate-limited requests

**Application Metrics**:
- `LatencyP50/P95/P99`: Processing latency percentiles
- `DLQRecordCount`: Records sent to Dead Letter Queue
- `WindowCompleteness`: % of records making it through window
- `DuplicateRecordDetected`: Duplicate dedup counter
- `WatermarkLagMs`: Gap between current time and watermark

### Tier 2: Health Metrics (10-second granularity, 7-day retention)

**Resource Usage**:
- `memory_usage_percentage`: JVM heap used
- `cpu_usage_percentage`: CPU utilization
- `task_manager_count`: Number of active Flink workers
- `kafka_broker_alive_count`: Kafka brokers responding

**State Backend**:
- `state_backend_used_bytes`: RocksDB size
- `state_read_count`: State lookups
- `state_write_count`: State updates

### Tier 3: Debug Metrics (1-minute granularity, 7-day retention)

**Checkpointing**:
- `checkpoint_size_bytes`: State snapshot size
- `checkpoint_aligned_vs_unaligned_ratio`: Checkpoint type
- `checkpoint_trigger_source`: What triggered checkpoint

**JVM**:
- `gc_pause_time_ms`: GC pause durations
- `gc_pause_count_per_minute`: GC frequency
- `gc_memory_freed_bytes`: Memory reclaimed per GC

---

## Section 3: Structured Logging

### Log Format

All logs are JSON with these fields:

```json
{
  "timestamp": "2025-01-13T10:30:45.123Z",
  "level": "INFO|WARN|ERROR",
  "logger": "order_processor",
  "message": "Order processed successfully",
  
  "correlation_id": "abc-123-def",  // Trace this order through pipeline
  "order_id": "ORD-12345",
  "customer_id": "CUST-789",
  "session_id": "sess-456",
  
  "operator": "enrichment",
  "latency_ms": 245,
  "status": "success|error",
  
  "error_type": "timeout|validation_error|duplicate|...",
  "error_code": "ERR-001",
  "error_message": "Customer API timeout after 30s",
  
  "environment": "prod",
  "environment_replica": "order-processor-1",
  "context": {
    "api_endpoint": "https://customer-api/v1/customers/789",
    "api_latency_ms": 5000,
    "cache_hit": false
  }
}
```

### CloudWatch Logs Insights Queries

**Trace single order through pipeline**:
```
fields @timestamp, operator, latency_ms, @message
| filter order_id = "ORD-12345"
| sort @timestamp asc
```

**Find all errors for past 1 hour**:
```
fields @timestamp, error_type, order_id, @message
| filter error_type in ["parse_error", "validation_error", "timeout"]
| stats count() as error_count by error_type
| sort error_count desc
```

**Latency percentiles**:
```
fields latency_ms
| filter latency_ms > 0
| stats pct(latency_ms, 50) as p50, pct(latency_ms, 95) as p95, pct(latency_ms, 99) as p99
```

**Find slow operators**:
```
fields operator, latency_ms
| stats avg(latency_ms) as avg_latency, max(latency_ms) as max_latency by operator
| sort max_latency desc
```

**Find DLQ spike cause**:
```
fields @timestamp, error_type, operator, order_id
| filter error_type in ["parse_error", "duplicate", "validation_error"]
| stats count() as error_count by bin(5m), error_type
| filter error_count > 100
```

---

## Section 4: Alert Severity Levels

| Severity | Definition | Action | Response Time |
|----------|-----------|--------|----------------|
| CRITICAL | Data loss, major feature broken | Page on-call, start incident | 5 min |
| HIGH | Degraded performance, approaching SLA breach | Create ticket, monitor closely | 1 hour |
| MEDIUM | Minor issue, might affect customers | Log, investigate when available | 4 hours |
| LOW | Informational, no action needed | Log only | N/A |

### CRITICAL Alarms (Page Immediately)

1. **DLQ Spike**: >100 records/min
   - Indicates: Data quality issue or parsing error
   - Expected: <10/min
   - Action: Check error type, rollback if recent deployment

2. **Checkpoint Failure**: >0 in 5 min
   - Indicates: State not persisting, restart would lose data
   - Expected: 0 failures
   - Action: Check S3 permissions, RocksDB disk space

3. **Kafka Broker Down**: <3 brokers alive
   - Indicates: Cluster degraded, can't tolerate another failure
   - Expected: 3 brokers
   - Action: Check AWS MSK console, request broker replacement

4. **Firehose Delivery Failed**: >0 in 1 min
   - Indicates: Records not reaching S3, buffering in Firehose
   - Expected: 0 failures
   - Action: Check IAM permission, S3 KMS key access

### HIGH Alarms (Investigate Within 1 Hour)

1. **Consumer Lag High**: >50K records
   - Indicates: Falling behind producer, latency increasing
   - SLO: <10K
   - Action: Check throughput, CPU, memory usage, enrichment API

2. **Processing Latency SLO Breach**: P99 > 5 sec
   - Indicates: 1% of orders stale (customer SLA violation)
   - SLO: P99 < 5 sec
   - Action: Check backpressure, CPU/memory, enrichment latency

3. **Window Completeness Low**: <95%
   - Indicates: Up to 5% of records not aggregated
   - SLO: >99%
   - Action: Check watermark, late arrivals, window trigger

---

## Section 5: Dashboards

### Dashboard 1: Health (Executives)

**Audience**: VP Engineering, Product Managers

**4 Golden Signals**:
1. Consumer lag (trending down = good)
2. DLQ rate (low = good)
3. Latency P99 (SLO met = green)
4. Window completeness (>95% = good)

**Refresh**: Every 60 seconds
**Use Case**: "Is the pipeline healthy?" (1-minute scan)

### Dashboard 2: Performance (SREs)

**Audience**: On-call SRE, performance engineers

**Components**:
- Throughput in vs. out (identify bottleneck)
- Checkpoint duration (healthy <10 sec)
- Memory/CPU trend (capacity planning)
- Latency percentiles (p50/p95/p99)
- Per-operator latency (drill down)

**Refresh**: Every 60 seconds
**Use Case**: "What's slow and why?" (5-minute troubleshooting)

### Dashboard 3: Errors (Debug)

**Audience**: On-call SRE, developers debugging

**Components**:
- DLQ breakdown by error type (pie chart)
- Error rate by operator (bar chart)
- Firehose delivery status (success/failure)
- Top 20 orders with most errors (table)
- Timeout trend over time (time series)

**Refresh**: Every 60 seconds
**Use Case**: "Why are we getting errors?" (incident response)

### Dashboard 4: Capacity (Planning)

**Audience**: Platform team, capacity planners

**Components**:
- CPU/Memory utilization trend (capacity)
- Kafka broker/Flink TM count (redundancy)
- State backend size (growth tracking)
- Network throughput (saturation)
- Firehose throttles (quota exceeded?)

**Refresh**: Every 5 minutes
**Use Case**: "Do we need to scale?" (capacity planning meeting)

---

## Section 6: Interview Q&A

### Q1: "How do you detect data loss?"

**30-Second Answer**:
"We use 5-layer defense: real-time DLQ metrics alert on unparseable records, checkpoint failure metrics signal state loss, consumer lag trending shows if we're falling behind, hourly reconciliation counts match Kafka to S3, and daily database validation checks for missing orders. Any layer can detect data loss within minutes."

**60-Second Answer**:
"Data loss typically comes from 3 sources: DLQ (unparseable records), state loss (checkpoint failures), or lag overflow (falling behind).

For DLQ: We track `DLQRecordCount` metric with alert at >100/min. When triggered, we immediately break down errors by type (parse error 80% → schema mismatch, duplicate 15% → dedup broken). Root cause usually found in 5 minutes.

For state loss: Checkpoint failure metric at >0 triggers page. On-call checks S3 permissions, RocksDB disk space. Usually fixed in 10 min.

For overflow: Consumer lag metric >50K indicates falling behind. If lag keeps growing = we're slower than input = will lose records within hours. On-call checks throughput, identifies bottleneck (usually enrichment API or backpressure).

Once data loss detected, we backfill from Kafka (30-day retention). Whole process: detect (1 min) + diagnose (5 min) + fix (10 min) + backfill (varies) = < 1 hour total."

**Technical Deep Dive**:
"The architecture uses:

1. **Per-operator metrics**: Each Flink operator reports `RecordsIn` and `RecordsOut`. If In > Out, we're losing records locally.

2. **CloudWatch Logs Insights queries** for forensics:
   - Match DLQ records back to source order_ids
   - Identify which partition/topic the loss occurred on
   - Determine if loss is random or systematic

3. **Daily batch validation**:
   ```python
   # Compare 24 hours of data
   kafka_count = count_records('orders.raw', '24h')
   dlq_count = count_dlq_records('24h')
   s3_count = count_s3_records('24h')
   
   assert s3_count >= kafka_count - dlq_count - expected_late_arrivals
   ```

4. **State backend checksum**:
   - Periodically hash state content
   - Compare before/after checkpoint
   - Alert if mismatch = state corruption

5. **Consumer group reset tracking**:
   - Monitor consumer offset resets
   - If offset goes backward = we're reprocessing
   - Correlate with state checkpoint time
   - Detect if loss is due to replay vs. true loss"

---

### Q2: "How do you know Flink is healthy?"

**30-Second Answer**:
"Dashboard shows 5 signals: lag trending down, DLQ rate <100/min, checkpoints succeeding, latency p99 <5s, window completeness >95%. If all 5 are green, pipeline is healthy. If any is red, we have a problem."

**60-Second Answer**:
"Flink health depends on:

1. **Lag**: `consumer_lag_records` < 10K (normal daily variation)
   - Why: Lag = latency delay. High lag = features stale.
   - Trending: Should be flat (steady-state) or declining (catching up). Growing = problem.

2. **DLQ**: `DLQRecordCount` rate < 10/min (occasional bad data expected)
   - Why: DLQ = unparseable or invalid records = we're dropping them
   - Alert: >100/min = data quality issue requires investigation

3. **Checkpoints**: Success rate 100% (every checkpoint should succeed)
   - Why: Checkpoint = save state to S3. Failure = state unrecoverable.
   - Alert: Any failure = page on-call (potential data loss risk)

4. **Latency**: P99 < 5 seconds (SLO from product team)
   - Why: >5s = features become stale = customer UX degrades
   - Check: p50 (typical), p95 (most), p99 (worst case)

5. **Completeness**: >95% of records in windows emitted
   - Why: <95% = up to 5% silent data loss in aggregations
   - Alert: <95% = investigate watermark, late arrivals, window trigger"

**Technical Deep Dive**:
"Under the hood, we're monitoring:

```
Health = f(lag, dlq_rate, checkpoint_success, latency_slo, completeness)

Green  = lag<10K && dlq_rate<10 && checkpoint_success=100% && p99<5s && completeness>95%
Yellow = lag 10-50K || dlq_rate 10-100 || p99 3-5s || completeness 90-95%
Red    = lag>50K || dlq_rate>100 || checkpoint_fail || p99>5s || completeness<90%
```

Flink exposes ~200 metrics. Most important 10 are on dashboard. Others available for deep debugging.

For SLA tracking:
- Measure latency per customer/region
- P99 < 5s globally
- P99 < 10s per region (accounts for network latency to region)
- If p99 breach, escalate to product team (might be acceptable depending on customer impact)

For operational metrics:
- Task manager stability (restarts = bad)
- GC pause time (>200ms = backpressure)
- State backend growth rate (should be flat after steady-state)
- Checkpoint size trend (growing = state leak)"

---

### Q3: "How would you debug a DLQ spike?"

**30-Second Answer**:
"Monitor shows DLQ spike. Query CloudWatch Logs by error_type to classify errors. If parse_error >80%, check source schema change. If duplicate >80%, check dedup window. If validation >80%, check business logic. Drill into sample errors, identify root cause, deploy fix, watch DLQ drop. Total: 15 minutes."

**60-Second Answer**:
"DLQ spike means records we can't process (bad JSON, missing fields, duplicates, etc.).

Process:

1. **Detect** (metric): DLQ rate alert fires (>100/min)
   - Page on-call
   - Timestamp: 10:30 UTC

2. **Assess** (metric): How many records affected?
   - Check accumulated DLQCount
   - Check trend: Growing or plateaued?
   - If plateaued = maybe code fix, else = maybe schema change

3. **Classify** (logs):
   ```
   fields error_type
   | filter dlq = true
   | stats count() as count by error_type
   | sort count desc
   ```
   Results:
   - parse_error: 8000 (80%)
   - duplicate: 1500 (15%)
   - validation: 500 (5%)

4. **Drill down** (logs):
   ```
   fields order_id, @message
   | filter dlq = true and error_type = "parse_error"
   | limit 5
   ```
   Results show: `JSON.parse() failed: Field 'cust_id' not found`
   
   Hypothesis: Source schema changed from 'customer_id' to 'cust_id'

5. **Verify** (external check):
   ```bash
   # Check recent source deployments
   curl https://source-api/schema | grep -i customer
   # Response: Field is now 'cust_id' (changed 10 min ago)
   ```

6. **Fix** (code):
   ```python
   # File: order_parser.py
   customer_id = order.get('cust_id') or order.get('customer_id')
   ```
   Deploy fix: Takes 2 minutes

7. **Verify** (metric):
   - Watch DLQ rate in real-time
   - After deployment: DLQ rate drops from 150/min to <10/min (takes ~1 min)
   - Latency p99 returns to normal (was elevated due to backpressure)

8. **Cleanup** (post-incident):
   - DLQ records are in S3 (not lost)
   - Can reprocess after fix
   - Add test case: `test_parser_handles_cust_id_field()`
   - Prevent future schema changes without notification (SLA with source team)"

**Technical Details**:

DLQ is actually a Kafka topic or S3 bucket where records go when they fail processing. We can reprocess DLQ records once root cause is fixed.

Common DLQ causes and fixes:
- Parse error (80%) → Parser update (2 min)
- Duplicate (15%) → Dedup window config (2 min)
- Validation (5%) → Business logic update (5 min)
- Timeout (rare) → Timeout config or API scale (10 min)

Monitoring improvements for next incident:
- Add per-operator error breakdown (know which op fails)
- Add sample error logs to metric (auto-diagnosis)
- Add source schema versioning webhook (catch schema changes before impact)

---

### Q4: "What's your biggest observability gap?"

**Answer**:
"3 gaps I'd address in priority order:

1. **Missing: Distributed tracing**
   - Currently: Correlation IDs in logs
   - Problem: Can trace through Flink/Firehose, but not into customer service enrichment API
   - Gap: Don't know if API slow due to API issue or network issue
   - Fix: Add X-Ray tracing to enrichment calls (1 week work)
   - Value: Would reduce enrichment latency debugging from 30 min to 5 min

2. **Missing: Synthetic tests**
   - Currently: No end-to-end monitoring of full pipeline outside of real traffic
   - Problem: If all orders pause (Kafka stopped producing), we don't detect it
   - Gap: Silent failure possible (no traffic = no metrics = no alert)
   - Fix: Inject synthetic test orders every 1 min (2 days work)
   - Value: Would detect stuck pipeline within 1 min vs. 30 min

3. **Missing: Data quality metrics**
   - Currently: Track that records make it through, not that they're correct
   - Problem: Could have silent correctness issue (e.g., all customer_ids set to 0)
   - Gap: Would only discover via daily database reconciliation (8 hours late)
   - Fix: Add schema validation + data profiling checks (2 weeks work)
   - Value: Would catch data quality issues within 1 hour vs. 8 hours

Top priority: Distributed tracing. Would unblock most frequent incidents (latency debugging)."

---

### Q5: "Walk me through the alerting strategy"

**Answer**:
"Alerting hierarchy:

**Level 1: Prevent False Positives (Don't Page on Random Noise)**
- Alarm threshold: 95th percentile of normal (not 99th)
- Evaluation periods: 2-3 periods (confirms not random spike)
- E.g., DLQ >100/min needs to persist for 2 minutes before alert

**Level 2: Page on CRITICAL (Immediate Business Impact)**
- DLQ spike: >100/min = 6K/hr = data quality issue
- Checkpoint failure: 0 failures expected = restart loses state
- Kafka down: <3 brokers = cluster degraded
- Firehose failed: Can't reach S3 = data loss

**Level 3: Alert on HIGH (Investigate Soon)**
- Consumer lag: >50K = catching up, latency increasing
- Latency SLO: P99 > 5s = customer feature degraded
- Memory: >85% = approaching OOM (buy time to scale)

**Level 4: Log LOW (Informational)**
- Deserialization errors: >5/min = data quality fine, just occasional bad record
- Duplicates: >10/min = dedup working but getting hammered
- This level goes to Slack #monitoring, not pages

**Tuning Strategy**:

First 2 weeks (learning phase):
- Alert at 50% of expected threshold
- Accept more false positives (better to over-alert early)
- Once on-call gets familiar, tighten thresholds

After 2 weeks (steady state):
- Threshold: 95th percentile of normal load
- Evaluation: 2-3 periods (avoid noise)
- Action: Every page gets a post-incident review (why did we get paged?)

**Per-Incident Improvement**:
- If false positive: Why did threshold not catch this? Tighten threshold or add condition.
- If missed alert: Why didn't we catch this sooner? Lower threshold or add new metric.
- Goal: Improve signal-to-noise ratio monthly

**Example**: DLQ Alert Tuning
- Week 1: Alert at >50/min (high false positive rate)
- Week 2: Alert at >75/min (fewer false positives)
- Month 1: Alert at >100/min (stable, rare false positives)
- If > 5 false positives/week: Investigate why (e.g., bad data source)
- If > 2 missed incidents: Lower threshold

**SLA for On-Call**:
- CRITICAL: 5 min to ack, 30 min to investigate
- HIGH: 1 hour to investigate
- AUTO-REMEDIATION: If <5 min to fix (e.g., restart Flink), auto-fix before page
- This requires runbooks: See ALERT_RUNBOOKS.md for step-by-step guides"

---

## Section 7: Operations Runbook

### Incident Response Playbook

**Step 1: Alert Fires** (0-5 min)
- On-call notified (PagerDuty/Slack)
- Open incident in Slack (auto-create channel #incident-123)
- Open dashboard for relevant service (Health/Performance/Errors)
- Create CloudWatch Logs Insights tab for logs

**Step 2: Assess** (5-10 min)
- Is alert still firing or already resolved? (transient spike vs. real issue)
- How many customers affected? (cosmetic vs. critical)
- Is manual intervention needed or auto-remedy running? (escalation decision)

**Step 3: Investigate** (10-20 min)
- Run relevant CloudWatch Logs Insights query from ALERT_RUNBOOKS.md
- Check recent deployments (git log --oneline -5)
- Check infrastructure changes (kubectl get events)
- Form hypothesis about root cause

**Step 4: Mitigate** (20-30 min)
- Execute fix from runbook (rollback, config change, scale, etc.)
- Monitor metrics to confirm fix is working
- Update Slack with status

**Step 5: Verify** (30-40 min)
- Confirm all alerts cleared
- Check for secondary issues (did fix cause cascading failures?)
- Verify no data loss (if incident involved DLQ)

**Step 6: Post-Incident** (40-60 min)
- Write incident summary (1 para)
- Identify root cause (1 sentence)
- Identify prevention (1 action item)
- Post in #incidents channel for team visibility

**Post-Incident Review** (within 48 hours)
- Full RCA meeting (what happened, why, how to prevent)
- Add test case to prevent regression
- Update runbooks if they were incomplete
- File bug/feature request for preventive measures

---

## Section 8: Metrics Implementation Code

See files:
- [custom_metrics.py](flink-java-app/src/main/python/custom_metrics.py) - Metrics collection from PyFlink
- [structured_logging.py](flink-java-app/src/main/python/structured_logging.py) - JSON logging with correlation IDs
- [cloudwatch_alarms.py](cloudwatch_alarms.py) - Alert definitions and thresholds
- [cloudwatch_dashboards.py](cloudwatch_dashboards.py) - Dashboard configurations

---

## Section 9: Interview Summary

**Your Observability Story** (2 min pitch):

"We designed observability around failure modes. For data loss, we have 5 layers: DLQ metrics, checkpoint health, consumer lag, hourly reconciliation, daily database validation. For latency, we track p50/p95/p99 plus per-operator breakdown plus resource utilization. For correctness, we monitor window completeness plus duplicate detection plus daily invariant checks.

We built 4 dashboards: Health (for executives), Performance (for SREs), Errors (for debugging), Capacity (for planning). On-call only has to look at 1 dashboard for their problem.

Alerting is tuned around SLOs, not raw metrics. DLQ alert fires at >100/min (6K/hr) not >10/min, because occasional errors are normal. This prevents alert fatigue while catching real issues within minutes.

For each alert, we have a runbook with step-by-step diagnosis. DLQ spike? Break down by error type (logs). Latency high? Check per-operator latency (metrics). Kafka down? Check broker count (metrics).

This lets on-call go from 'something is wrong' to 'fix deployed' in 15 minutes, vs. 2 hours with logging-based debugging."

**Key Takeaway for Interviewer**:
"We treat observability as infrastructure, not afterthought. It's designed around failure modes, not metrics we happen to have. This is why we can detect and fix issues in 15 minutes instead of hours."

---

## Appendix: Dashboard Screenshots

(Would include JSON export of each dashboard for copy/paste into CloudWatch)

See: [cloudwatch_dashboards.py](cloudwatch_dashboards.py)

## Appendix: Metric Thresholds Reference

| Metric | Normal | Warning | Critical |
|--------|--------|---------|----------|
| consumer_lag_records | <5K | 10-50K | >50K |
| DLQRecordCount rate | <10/min | 10-100/min | >100/min |
| LatencyP99 | <2s | 3-5s | >5s |
| WindowCompleteness | >99% | 95-99% | <95% |
| memory_usage % | <70% | 70-85% | >85% |
| cpu_usage % | <70% | 70-90% | >90% |
| checkpoint_duration_ms | <10s | 10-30s | >30s |
| checkpoint_failures | 0 | N/A | >0 |
| kafka_broker_alive_count | 3 | 2 | <2 |
| firehose_failed_put | 0 | N/A | >0 |

