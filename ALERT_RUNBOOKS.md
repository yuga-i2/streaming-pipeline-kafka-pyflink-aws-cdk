# Alert Runbooks
## Step-by-Step Incident Response Guide

---

## Table of Contents

1. [DLQ Spike - CRITICAL](#dlq-spike---critical)
2. [Checkpoint Failure - CRITICAL](#checkpoint-failure---critical)
3. [Kafka Broker Down - CRITICAL](#kafka-broker-down---critical)
4. [Firehose Delivery Failure - CRITICAL](#firehose-delivery-failure---critical)
5. [Consumer Lag High - HIGH](#consumer-lag-high---high)
6. [Processing Latency SLO Breach - HIGH](#processing-latency-slo-breach---high)
7. [Window Completeness Low - HIGH](#window-completeness-low---high)
8. [Memory Usage High - MEDIUM](#memory-usage-high---medium)
9. [Checkpoint Duration High - MEDIUM](#checkpoint-duration-high---medium)

---

## DLQ Spike - CRITICAL

**Alert**: `dlq-spike-critical` triggered (>100 records/min in DLQ)

**Expected Impact**: Data loss (unparseable/invalid records are being discarded)

**Time to Fix**: 5-15 minutes (typically)

### Step 1: Assess (1 min)

```bash
# 1. Check current DLQ rate
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name DLQRecordCount \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# 2. Check last 5 minutes of error logs
aws logs tail ecommerce-streaming --follow --since 5m | grep error_type | jq .error_type | sort | uniq -c
```

### Step 2: Classify (2 min)

**CloudWatch Logs Insights Query:**
```
fields @timestamp, order_id, error_type, @message
| filter dlq = true
| stats count() as count by error_type
| sort count desc
```

**What each error type indicates**:
- `parse_error` (most common): JSON is malformed → Check source data schema
- `validation_error`: Required field missing → Check business logic rules
- `duplicate`: Already seen this order_id → Check dedup window
- `timeout`: External API didn't respond → Check enrichment service
- `external_api_error`: API returned error → Check downstream service logs

### Step 3: Root Cause

**If parse_error is >80% of DLQ:**
```bash
# Get sample of failed records
aws logs start-query \
  --log-group-name ecommerce-streaming \
  --start-time $(date -d '30 minutes ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields order_id, @message | filter error_type="parse_error" | limit 10'
```

**Likely causes by recent changes**:
- Recent deployment: Code change bug (rollback required)
- Recent schema change: Source system updated field format (need parser fix)
- New traffic pattern: Different customer sending weird data (add validation)

### Step 4: Immediate Fix

**Option A: Code Bug (Most Likely)**
```bash
# 1. Identify which commit caused it
git log --oneline -10

# 2. Rollback if recent deployment
git revert <commit-hash>
git push origin main

# 3. Monitor DLQ rate while rolling out
watch -n 5 'aws cloudwatch get-metric-statistics --namespace ecommerce-streaming --metric-name DLQRecordCount --start-time $(date -u -d "5 minutes ago" +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S) --period 60 --statistics Sum | jq ".Datapoints[-1].Sum"'
```

**Option B: Source Data Schema Changed**
```bash
# 1. Check source data sample
kafka-console-consumer --bootstrap-servers $KAFKA_BROKER \
  --topic orders.raw \
  --from-beginning \
  --max-messages 10 | head -3

# 2. If schema changed, update parser code
# Example: source_system.py
def parse_order(json_str: str) -> Dict:
    data = json.loads(json_str)
    # Old code expected "customer_id"
    # New code sends "cust_id" instead
    return {
        "order_id": data["order_id"],
        "customer_id": data.get("cust_id") or data.get("customer_id")
    }

# 3. Deploy fix
git commit -am "Handle schema change: cust_id -> customer_id"
git push origin main
```

**Option C: Validation Rule Changed**
```bash
# 1. Check which orders are failing validation
aws logs start-query \
  --log-group-name ecommerce-streaming \
  --start-time $(date -d '10 minutes ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields order_id, validation_error | filter error_type="validation_error" | limit 20'

# 2. Determine if rule is too strict
# Example: orders < $100 might be test data
if order.total < 100:
    # Is this legitimate? Check with product team

# 3. Update validation if needed
# Example: allow $0-1 orders (promo/test)
if not (0 <= order.total <= 999999):
    raise ValidationError(f"Order amount out of range: ${order.total}")
```

### Step 5: Verify (2 min)

```bash
# 1. Watch DLQ rate drop
# Should see DLQ rate return to <10/min within 2-3 minutes of deployment

# 2. Confirm no other errors
aws logs start-query \
  --log-group-name ecommerce-streaming \
  --start-time $(date -d '3 minutes ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields error_type | stats count() by error_type'

# 3. If >1000 errors during incident, check for data loss
# Compare Kafka record count vs. S3 records
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions" | grep Value
```

### Step 6: Post-Incident (5 min)

```bash
# 1. Document what happened
# File: INCIDENTS.md
# Date: 2025-01-13
# Issue: Parse errors on 50K records due to schema change in source API
# Root Cause: Source system changed "customer_id" -> "cust_id"
# Fix: Updated parser to handle both field names
# Time to Fix: 8 minutes
# Data Loss: 0 (all records in DLQ, can reprocess after fix)

# 2. Add test case to prevent regression
# File: tests/test_order_parser.py
def test_parser_handles_old_schema():
    old_schema_json = '{"order_id": "1", "customer_id": "CUST-123"}'
    assert parse_order(old_schema_json)["customer_id"] == "CUST-123"

def test_parser_handles_new_schema():
    new_schema_json = '{"order_id": "1", "cust_id": "CUST-123"}'
    assert parse_order(new_schema_json)["customer_id"] == "CUST-123"

# 3. Reprocess affected records
# DLQ is in S3, can re-ingest after fix is deployed
```

### Timeline

| Time | Action | Duration |
|------|--------|----------|
| T+0 | Alert triggered, on-call notified | - |
| T+1 | Assess: Check DLQ rate, recent deployments | 1 min |
| T+3 | Classify: Break down errors by type | 2 min |
| T+8 | Root Cause: Find source of errors (code, schema, data) | 5 min |
| T+10 | Fix: Rollback or code change deployed | 2 min |
| T+12 | Verify: DLQ rate dropping, no cascading errors | 2 min |
| T+15 | Post-incident: Document, add test, plan remediation | 5 min |

**Total Time to Fix: 15 minutes**

---

## Checkpoint Failure - CRITICAL

**Alert**: `checkpoint-failure-critical` triggered (>0 failures in 5 min window)

**Expected Impact**: Job can't save state. On restart, state is lost = data loss risk.

**Time to Fix**: 5-20 minutes

### Step 1: Assess (1 min)

```bash
# 1. Check Flink logs for checkpoint error
kubectl logs -l app=flink-taskmanager -f --tail=50 | grep -i checkpoint

# Example output:
# 2025-01-13 10:30:45 ERROR CheckpointCoordinator: 
# IOException: Access Denied to s3://checkpoint-bucket/state

# 2. Check if job is still running or crashed
kubectl get pods -l app=flink-taskmanager
# STATUS: Running or CrashLoopBackOff?
```

### Step 2: Identify Failure Type (2 min)

**Check Flink Web UI** (if available):
```bash
# Get Flink job manager external IP
kubectl get svc flink-jobmanager
# Navigate to: http://<IP>:8081/jobs

# Look for "Checkpoint" tab, see last failed checkpoint
# Error message will tell you:
# - "Access Denied" = IAM permission issue
# - "Disk full" = RocksDB storage full
# - "Timeout" = S3 slow or network issue
```

**Or check logs directly:**
```bash
# Get last 100 lines of Flink job manager log
kubectl logs -l app=flink-jobmanager --tail=100 | grep -A5 -B5 "Checkpoint"
```

### Step 3: Common Fixes

**A. S3 Permission Denied**
```bash
# 1. Verify IAM role has s3:PutObject on checkpoint bucket
aws iam get-role-policy \
  --role-name FlinkTaskExecutorRole \
  --policy-name FlinkCheckpointPolicy

# 2. If missing, add permission (via CDK or AWS CLI)
aws iam put-role-policy \
  --role-name FlinkTaskExecutorRole \
  --policy-name FlinkCheckpointPolicy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["s3:PutObject", "s3:GetObject"],
        "Resource": "arn:aws:s3:::checkpoint-bucket/*"
      }
    ]
  }'

# 3. Redeploy Flink job
kubectl rollout restart deployment flink-taskmanager
```

**B. KMS Key Denied**
```bash
# 1. Check if checkpoint bucket is encrypted with customer KMS key
aws s3api get-bucket-encryption --bucket checkpoint-bucket
# Should show: "SSEAlgorithm": "aws:kms"

# 2. Verify KMS key policy allows role to decrypt
aws kms get-key-policy \
  --key-id arn:aws:kms:us-east-1:ACCOUNT:key/12345678-1234-1234-1234-123456789012 \
  --policy-name default

# 3. If role not in key policy, add grant
aws kms create-grant \
  --key-id arn:aws:kms:us-east-1:ACCOUNT:key/12345678-1234-1234-1234-123456789012 \
  --grantee-principal arn:aws:iam::ACCOUNT:role/FlinkTaskExecutorRole \
  --operations Decrypt Encrypt GenerateDataKey
```

**C. RocksDB Disk Full**
```bash
# 1. Check task manager disk usage
kubectl exec -it flink-taskmanager-0 -- df -h

# 2. If /data is 90%+ full, we need cleanup
# Option 1: Increase disk (PVC)
kubectl patch pvc flink-state-pvc -p '{"spec":{"resources":{"requests":{"storage":"100Gi"}}}}'

# Option 2: Clean old checkpoints
aws s3 rm s3://checkpoint-bucket/ --recursive \
  --exclude "*" \
  --include "*/chk-*/shared/*" \
  --older-than 7

# 3. Restart Flink job to clear state
kubectl delete pod -l app=flink-taskmanager
```

**D. S3 Upload Timeout**
```bash
# 1. Check S3 network latency
# Measure time to upload 1GB to S3
time aws s3 cp /dev/urandom s3://checkpoint-bucket/test-1gb --sse AES256 --expect-100-continue

# 2. If slow (>30s), increase checkpoint timeout in Flink config
# File: flink-application-properties.json
{
  "Checkpoint": {
    "CheckpointingMode": "EXACTLY_ONCE",
    "CheckpointInterval": "60000",  # 60 seconds between checkpoints
    "CheckpointTimeout": "600000"   # 10 minutes to complete (increase if slow)
  }
}

# 3. Or reduce checkpoint frequency
# Only checkpoint every 5 minutes instead of 1 minute
```

### Step 4: Verify Fix

```bash
# 1. Trigger manual checkpoint
kubectl exec -it flink-jobmanager-0 -- \
  curl http://localhost:6123/jobs/<job-id>/checkpoints/trigger

# 2. Wait for checkpoint to complete
# If successful: job logs show "Checkpoint completed in XXX ms"
# If failed: error message appears

# 3. Check next automatic checkpoint succeeds
# Look for: "Checkpoint X completed in Y seconds"
```

### Step 5: Post-Incident

```bash
# 1. Did we lose data?
# Check S3: Last checkpoint timestamp < failure timestamp?
# If yes, records after last checkpoint are lost

# 2. Reprocess lost records (if necessary)
# Kafka stores messages for 30 days
# Can reset consumer offset to reprocess

# 3. Add test to prevent regression
# Automated test: Try to checkpoint with filled disk, verify error handling
```

---

## Kafka Broker Down - CRITICAL

**Alert**: `kafka-broker-down-critical` triggered (< 3 brokers alive)

**Expected Impact**: Possible data loss if 2nd broker fails before recovery

**Time to Fix**: 5-10 minutes (requires AWS intervention)

### Step 1: Assess (1 min)

```bash
# 1. Check which brokers are down
aws msk describe-cluster \
  --cluster-arn arn:aws:kafka:us-east-1:ACCOUNT:cluster/OrderProcessing/* \
  --query 'ClusterInfo.BrokerNodeGroupInfo' | jq '.BrokerNodes[] | {BrokerNodeId, ClientSubnets, StorageInfo}'

# 2. Check broker health in MSK console
aws msk list-brokers \
  --cluster-arn arn:aws:kafka:us-east-1:ACCOUNT:cluster/OrderProcessing/* | \
  jq '.BrokerMetadataList[] | {BrokerId, ControllerStatus}'

# 3. Try to produce/consume
kafka-console-producer --bootstrap-servers broker1:9092,broker2:9092,broker3:9092 \
  --topic test \
  --message "test" \
  --timeout 5000

# If timeout = brokers not responding
```

### Step 2: Action

**Most likely**: AWS auto-recovery will fix (takes 5-15 min)

**If manual intervention needed:**
```bash
# 1. Check AWS MSK console for broker failure notifications
# AWS usually auto-replaces failed brokers

# 2. If stuck, reboot broker manually
aws msk reboot-broker \
  --cluster-arn arn:aws:kafka:us-east-1:ACCOUNT:cluster/OrderProcessing/* \
  --broker-ids 2  # Reboot broker 2

# 3. Verify broker comes back
aws msk describe-cluster --cluster-arn ... | jq '.ClusterInfo.BrokerNodeGroupInfo'
# Wait for all BrokerNodes to show Status: "ACTIVE"
```

### Step 3: Verify Cluster Health

```bash
# 1. Check all brokers are responding
for broker in broker1 broker2 broker3; do
  echo "Testing $broker..."
  kafka-broker-api-versions --bootstrap-server $broker:9092 || echo "FAILED"
done

# 2. Check under-replicated partitions (if any)
kafka-run-class kafka.tools.JmxTool \
  --object-name "kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions" | grep Value

# Should be 0 (all replicas in sync)

# 3. Check consumer lag (should be normal)
kafka-consumer-groups --bootstrap-servers brokers:9092 \
  --group order-processor \
  --describe | tail -20
```

### Step 4: Post-Incident

```bash
# 1. Investigate why broker failed
# Check AWS Health Dashboard for infrastructure issues

# 2. Ensure backup plan
# If this happens again:
# - Auto-scaling group should replace failed broker automatically
# - If not, create PagerDuty escalation

# 3. Plan capacity
# 3 brokers is minimum for HA
# With 3 brokers:
# - Can lose 1 and still operate (degraded)
# - Can't lose 2 without total outage
# Consider 4+ brokers for higher availability
```

---

## Firehose Delivery Failure - CRITICAL

**Alert**: `firehose-delivery-failure-critical` triggered (>0 failed puts in 1 min)

**Expected Impact**: Records buffered in Firehose but not in S3. Buffer full after 5 min = data loss.

**Time to Fix**: 5-10 minutes

### Step 1: Assess (1 min)

```bash
# 1. Check Firehose stream status
aws firehose describe-delivery-stream \
  --delivery-stream-name order-firehose

# Look for:
# - StreamStatus: ACTIVE or PROBLEM?
# - LastUpdateTimestamp: Recent?

# 2. Check delivery metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Firehose \
  --metric-name DeliveryToS3.Records \
  --dimensions Name=DeliveryStreamName,Value=order-firehose \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# 3. Check buffer status
aws firehose describe-delivery-stream \
  --delivery-stream-name order-firehose | \
  jq '.DeliveryStreamDescription.S3DestinationDescription'
```

### Step 2: Identify Failure Cause (2 min)

**Most Common:**

**A. S3 Access Denied**
```bash
# 1. Check Firehose IAM role
aws iam get-role-policy \
  --role-name FirehoseDeliveryRole \
  --policy-name FirehoseS3Policy

# 2. Verify it has s3:PutObject on the bucket
# Should include:
# "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"]
# "Resource": "arn:aws:s3:::order-firehose-bucket/*"

# 3. If missing, add permission
aws iam put-role-policy \
  --role-name FirehoseDeliveryRole \
  --policy-name FirehoseS3Policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::order-firehose-bucket/*"
    }]
  }'

# 4. Firehose retries automatically, should resume after 1-2 min
```

**B. KMS Key Denied (if bucket encrypted)**
```bash
# 1. Check S3 bucket encryption
aws s3api get-bucket-encryption --bucket order-firehose-bucket
# Should show KMS key ARN

# 2. Grant Firehose role access to key
aws kms create-grant \
  --key-id arn:aws:kms:us-east-1:ACCOUNT:key/KEY-ID \
  --grantee-principal arn:aws:iam::ACCOUNT:role/FirehoseDeliveryRole \
  --operations Decrypt Encrypt GenerateDataKey

# 3. Resume delivery (automatic after grant)
```

**C. S3 Bucket Full or Quota Exceeded**
```bash
# 1. Check S3 bucket size
aws s3 ls s3://order-firehose-bucket/ --summarize | tail -5

# 2. Check for quota limits
aws service-quotas get-service-quota \
  --service-code s3 \
  --quota-code L-DC2B2D7E  # PutObject rate

# 3. If quota hit, request increase (takes 24-48 hours)
aws service-quotas request-service-quota-increase \
  --service-code s3 \
  --quota-code L-DC2B2D7E \
  --desired-value 30000  # 30K requests/second

# 4. Meanwhile, scale up Firehose buffer settings
aws firehose update-delivery-stream \
  --delivery-stream-name order-firehose \
  --s3-destination-update '{
    "RoleARN": "arn:aws:iam::ACCOUNT:role/FirehoseDeliveryRole",
    "BucketARN": "arn:aws:s3:::order-firehose-bucket",
    "BufferingHints": {
      "SizeInMBs": 256,      # Increase from 128MB
      "IntervalInSeconds": 60
    }
  }'
```

**D. S3 Network Latency (rare)**
```bash
# 1. Test S3 upload latency
time dd if=/dev/zero bs=1M count=100 | \
  aws s3 cp - s3://order-firehose-bucket/latency-test --sse AES256

# 2. If >10 seconds for 100MB, network is slow
# Options:
# - Use S3 Transfer Acceleration (faster network)
# - Reduce Firehose batch size (deliver more frequently)
# - Contact AWS support for network issue

aws firehose update-delivery-stream \
  --delivery-stream-name order-firehose \
  --s3-destination-update '{
    "BufferingHints": {
      "SizeInMBs": 64,  # Smaller batches = more frequent uploads
      "IntervalInSeconds": 30
    }
  }'
```

### Step 3: Verify Fix

```bash
# 1. Monitor Firehose delivery success rate
aws cloudwatch get-metric-statistics \
  --namespace AWS/Firehose \
  --metric-name DeliveryToS3.Success \
  --dimensions Name=DeliveryStreamName,Value=order-firehose \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# Should see records being delivered

# 2. Check Firehose buffer (should decline)
aws firehose describe-delivery-stream \
  --delivery-stream-name order-firehose | \
  jq '.DeliveryStreamDescription | {StreamStatus, LastUpdateTimestamp}'

# Status should go back to ACTIVE
```

### Step 4: Post-Incident

```bash
# 1. Check for data loss
# Firehose buffered for ~5 minutes before failure
# Count records in S3 from 10 min ago to now
# Calculate expected vs. actual

# 2. Did we lose any records?
# Check Firehose CloudWatch metrics
# "DeliveryToS3.Records" should match Flink "RecordsOut"

# 3. Plan to prevent
# Increase monitoring alert threshold
# Add backup delivery path (SNS, SQS) for critical data
```

---

## Consumer Lag High - HIGH

**Alert**: `kafka-consumer-lag-high` triggered (>50K records)

**Expected Impact**: Delayed real-time features (dashboard data stale by X minutes)

**Time to Fix**: 5-30 minutes (depends on cause)

### Step 1: Assess (1 min)

```bash
# 1. Check consumer lag per partition
kafka-consumer-groups --bootstrap-servers brokers:9092 \
  --group order-processor \
  --describe

# Output example:
# TOPIC         PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG
# orders.raw    0          50000           75000           25000
# orders.raw    1          40000           95000           55000  <- HIGH
# orders.raw    2          45000           60000           15000

# Total lag: 95000

# 2. Check if lag is growing or stable
# Run same command every 30 seconds
watch -n 30 'kafka-consumer-groups --bootstrap-servers brokers:9092 --group order-processor --describe'

# Growing lag = falling behind (serious)
# Stable lag = temporary spike (OK to monitor)
```

### Step 2: Identify Bottleneck (2 min)

```bash
# Check Flink throughput
# If RecordsIn > RecordsOut = processing slower than input

# Query Flink metrics
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name RecordsIn \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name RecordsOut \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# Compare: RecordsIn vs RecordsOut
# If RecordsOut < RecordsIn = we're too slow
```

### Step 3: Root Cause

**A. Enrichment API is Slow**
```bash
# 1. Check enrichment service latency
# If latency > 500ms per call, that's the bottleneck

# Option 1: Increase timeout
# File: KafkaStreamingJob.java
enrichment_timeout = Duration.seconds(30)  # Increase from 10s

# Option 2: Add caching (local or Redis)
# Cache customer data for 1 hour
customer_cache = TTL_Cache(ttl_seconds=3600)

def enrich_order(order):
    if order["customer_id"] not in customer_cache:
        customer_cache[order["customer_id"]] = fetch_customer_api(order["customer_id"])
    return {..., "customer": customer_cache[order["customer_id"]]}
```

**B. Flink Resource Constraint (CPU, Memory)**
```bash
# 1. Check Flink task manager resource usage
kubectl top pod -l app=flink-taskmanager

# Example output:
# NAME              CPU(cores)   MEMORY(Mi)
# flink-taskmanager-0   2000m        7800Mi  <- 80% memory = constraint
# flink-taskmanager-1   1900m        7200Mi
# flink-taskmanager-2   1950m        7900Mi

# 2. If high utilization, scale up
# Increase task manager replicas
kubectl scale deployment flink-taskmanager --replicas=5

# Or increase resources per replica
kubectl set resources deployment flink-taskmanager \
  --limits cpu=4000m,memory=16Gi \
  --requests cpu=2000m,memory=8Gi

# 3. Increase parallelism to use new resources
# File: KafkaStreamingJob.java
env.setParallelism(8)  # Increase from 4
```

**C. Windowing Issue (Events Not Triggering Window)**
```bash
# 1. Check window emit rate
# Should be emitting windows every 5 minutes

aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name window_emit_count \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Sum

# 2. If emits dropping, check watermark
# Watermark stuck = windows not closing

aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name WatermarkLagMs \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# If > 60 seconds = watermark stuck (upstream issue)
```

**D. Backpressure (Downstream Full)**
```bash
# 1. Check if Firehose is accepting data
aws cloudwatch get-metric-statistics \
  --namespace AWS/Firehose \
  --metric-name DeliveryToS3.Records \
  --dimensions Name=DeliveryStreamName,Value=order-firehose \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# If 0 records being delivered = Firehose is throttled
# See "Firehose Delivery Failure" runbook
```

### Step 4: Fix Based on Cause

**If Enrichment API:**
- Add caching (5 min fix)
- Increase timeout (1 min fix)
- Scale enrichment service (contact backend team)

**If Flink Resource:**
- Scale up task managers (5 min)
- Increase parallelism (5 min)

**If Windowing:**
- Check watermark lag (see Water mark lag runbook)

**If Backpressure:**
- Check Firehose (see Firehose runbook)

### Step 5: Verify

```bash
# 1. Monitor lag decreasing
watch -n 30 'kafka-consumer-groups --bootstrap-servers brokers:9092 --group order-processor --describe | grep -E "LAG|orders.raw"'

# Lag should start decreasing within 2-5 minutes

# 2. Check if stabilizing
# Once lag stops growing = fix is working
# Lag will slowly decrease as we catch up

# 3. Correlate with latency SLO
# Lag should correlate with latency
# Higher lag = older data = higher latency
```

---

## Processing Latency SLO Breach - HIGH

**Alert**: `processing-latency-slo-breach` triggered (p99 > 5 seconds)

**Expected Impact**: 1% of customers see stale data (real-time features broken)

**Time to Fix**: 5-15 minutes

### Step 1: Assess (1 min)

```bash
# 1. Check current latency distribution
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name LatencyP50 \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# 2. Check all percentiles
for percentile in P50 P95 P99; do
  echo "=== $percentile ==="
  aws cloudwatch get-metric-statistics \
    --namespace ecommerce-streaming \
    --metric-name Latency$percentile \
    --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 60 \
    --statistics Average
done
```

### Step 2: Identify Which Operator is Slow (2 min)

```bash
# CloudWatch Logs Insights: Latency per operator
fields operator, latency_ms
| stats avg(latency_ms) as avg, pct(latency_ms, 95) as p95, pct(latency_ms, 99) as p99 by operator
| sort p99 desc

# Example output:
# operator        avg    p95    p99
# enrichment      850    1400   3200  <- SLOW
# deserialization 15     25     40
# validation      30     50     80
# aggregation     200    600    1200
# firehose_delay  500    1200   2100

# Enrichment is taking 3.2 seconds in p99 case!
```

### Step 3: Drill Into Slow Operator (2 min)

```bash
# If enrichment is slow:
fields @timestamp, order_id, enrichment_api_latency, enrichment_cache_hit
| filter operator = "enrichment"
| stats avg(enrichment_api_latency) as api_latency, 
        avg(enrichment_cache_hit) as cache_hit_rate by bin(1m)

# Check if:
# 1. API latency is high (>1000ms)?
# 2. Cache hit rate is low (<80%)?

# Get sample slow requests
fields order_id, enrichment_api_latency, customer_id
| filter operator = "enrichment" and enrichment_api_latency > 2000
| limit 20

# Check if they're all same customer = maybe customer service is slow
```

### Step 4: Fix

**If Enrichment API is Slow:**
```bash
# Option 1: Increase cache TTL (5 min fix)
# File: KafkaStreamingJob.java
customer_cache = TTLCache(ttl_seconds=3600)  # 1 hour instead of 10 min

# Option 2: Add local Redis cache (10 min fix)
# File: KafkaStreamingJob.java
redis_client = redis.Redis(host='redis.default', port=6379)

def enrich_order(order):
    customer_id = order["customer_id"]
    
    # Try cache first
    cached = redis_client.get(f"customer:{customer_id}")
    if cached:
        return {..., "customer": json.loads(cached)}
    
    # Cache miss, fetch from API
    customer = fetch_customer_api(customer_id)
    redis_client.setex(f"customer:{customer_id}", 3600, json.dumps(customer))
    return {..., "customer": customer}
```

**If Firehose is Slow:**
```bash
# Option 1: Increase buffer size (Firehose batches more before upload)
aws firehose update-delivery-stream \
  --delivery-stream-name order-firehose \
  --s3-destination-update '{
    "BufferingHints": {
      "SizeInMBs": 256,  # Upload when 256MB buffer reached
      "IntervalInSeconds": 60  # Or every 60 seconds
    }
  }'

# Option 2: Add parallel Firehose streams (if size > 5 MB/s)
# Create 2nd Firehose stream
# Split traffic: Even order_ids -> Stream 1, Odd -> Stream 2
```

**If Backpressure (Task Manager Full):**
```bash
# Scale up Flink
kubectl scale deployment flink-taskmanager --replicas=8

# Increase buffer pool (allow more queued records)
# File: flink-config.yaml
taskmanager.network.memory.buffers: 2048  # Increase from 1024
```

### Step 5: Verify

```bash
# 1. Watch latency decrease
watch -n 30 'aws cloudwatch get-metric-statistics --namespace ecommerce-streaming --metric-name LatencyP99 --start-time $(date -u -d "5 min ago" +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S) --period 60 --statistics Average | jq ".Datapoints[-1].Average"'

# Should see latency drop within 1-2 minutes

# 2. Confirm p99 < 5 seconds
# Alert should clear automatically

# 3. Check if fix is sustainable (trend)
# Monitor for next 30 minutes to ensure latency stays low
```

---

## Window Completeness Low - HIGH

**Alert**: `window-completeness-low` triggered (< 95%)

**Expected Impact**: Up to 5%+ of records missing from aggregations

**Time to Fix**: 10-20 minutes

### Step 1: Assess (1 min)

```bash
# 1. Check current window completeness
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name WindowCompleteness \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics Average

# Example:
# Time | Completeness
# 10:00 | 100%
# 10:05 | 100%
# 10:10 | 87%  <- DROP
# 10:15 | 92%
# 10:20 | 91%

# 2. Get specific window stats
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name WindowCompleteness \
  --dimensions Name=window_id,Value=window-2025-01-13-10-10 \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average
```

### Step 2: Determine Type of Loss (2 min)

```bash
# Check if records are in DLQ or just missing
aws logs start-query \
  --log-group-name ecommerce-streaming \
  --start-time $(date -d '10 minutes ago' +%s) \
  --end-time $(date +%s) \
  --query-string '
    fields @timestamp, window_id, records_in, records_out, records_late
    | filter window_id = "window-2025-01-13-10-10"
  '

# Example output:
# Time | window_id | in | out | late
# 10:10 | window-2025-01-13-10-10 | 10000 | 9200 | 500
# Gap: 1000 - 500 = 500 records unaccounted (ERROR!)

# Possible reasons:
# 1. Late arrivals beyond window (after allowedLateness expires)
# 2. Watermark never advanced (stuck processing)
# 3. State backend lost records (corruption)
# 4. Window never closed (triggered=false)
```

### Step 3: Root Cause

**A. Late Arrivals Beyond Window**
```bash
# 1. Check how many late arrivals per window
fields window_id, records_late
| filter records_late > 0
| stats sum(records_late) as total_late by window_id

# 2. If > 5% of window = issue with data freshness
# Records are arriving 5+ minutes late!

# Root cause: Either
# - Source system is delaying messages
# - Watermark is stuck (see B below)

# Fix: Increase allowedLateness
# File: KafkaStreamingJob.java
.window(TumblingEventTimeWindow.of(Time.minutes(5)))
 .allowedLateness(Time.minutes(10))  # Accept records 10 min late

# This increases correctness but also latency
```

**B. Watermark Stuck**
```bash
# 1. Check watermark lag
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name WatermarkLagMs \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# Watermark = "current time" in Flink
# If stuck = Flink hasn't processed records for X minutes
# If stuck for >5 min = windows never close = completeness drops

# 2. If stuck, likely upstream issue
# Check if Kafka is producing:
kafka-console-consumer --bootstrap-servers brokers:9092 \
  --topic orders.raw \
  --max-messages 5 | head -5

# 3. If records exist in Kafka = Flink is stalled
# Check Flink logs:
kubectl logs -l app=flink-taskmanager | tail -50 | grep -i stuck

# 4. Fix: Restart Flink
kubectl delete pod -l app=flink-taskmanager
# Watermark will reset to current time
```

**C. State Backend Corruption**
```bash
# 1. Check state backend metrics
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name StateBackendReadCount \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Sum

# Compare:
# RecordsIn: 10000
# RecordsOut: 9200
# StateReads: 9200
# StateWrites: 9200
# If StateWrites < RecordsIn = state corruption

# 2. If corrupted, restore from checkpoint
# Find latest good checkpoint
aws s3 ls s3://checkpoint-bucket/ --recursive | tail -10

# 3. Restart Flink with checkpoint
kubectl delete pod -l app=flink-taskmanager
# Flink will restore from latest checkpoint
# Might lose last few minutes, but state will be consistent
```

**D. Window Never Triggered**
```bash
# 1. Check if window is emitting
aws logs start-query \
  --log-group-name ecommerce-streaming \
  --start-time $(date -d '30 minutes ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields window_id | stats count() by window_id | sort count desc'

# Should see window-2025-01-13-10-00, 10-05, 10-10, etc.
# If missing windows = trigger logic broken

# 2. Check window config:
# File: KafkaStreamingJob.java
.window(TumblingEventTimeWindow.of(Time.minutes(5)))
 .trigger(EventTimeTrigger.create())  # Or custom trigger?

# If custom trigger = might have bug
# Revert to standard EventTimeTrigger
```

### Step 4: Fix Based on Root Cause

**Late arrivals**: Increase allowedLateness (but accept higher latency)
**Watermark stuck**: Restart Flink
**State corruption**: Restore from checkpoint
**Window trigger bug**: Fix trigger logic

### Step 5: Verify

```bash
# 1. Check window completeness improving
watch -n 300 'aws cloudwatch get-metric-statistics --namespace ecommerce-streaming --metric-name WindowCompleteness --start-time $(date -u -d "30 min ago" +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S) --period 300 --statistics Average | tail -5'

# Should see values returning to >95%

# 2. Check new windows are emitting
fields window_id
| filter @timestamp > "2025-01-13T10:20:00" 
| stats count() as windows by bin(5m)

# Should see at least 1 window every 5 minutes
```

---

## Memory Usage High - MEDIUM

**Alert**: `memory-usage-high` triggered (>85%)

**Expected Impact**: If memory reaches 95%, task manager OOMKills (restart loses state)

**Time to Fix**: 5-30 minutes (depends on cause)

### Step 1: Assess (1 min)

```bash
# 1. Check memory usage trend
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name memory_usage_percentage \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# Example trend:
# 10:00 | 60%
# 10:10 | 65%
# 10:20 | 75%
# 10:30 | 85%
# 10:40 | 88%

# Growing trend = MEMORY LEAK (serious)
# Stable at 85% = Temporary spike (OK, but monitor)

# 2. Get detailed breakdown
kubectl exec -it flink-taskmanager-0 -- jmap -heap 1 | head -20

# Shows:
# Heap Usage: X% (how much of heap allocated)
# Heap Committed: Y GB
# Non-Heap: Z MB
```

### Step 2: Determine Cause (2 min)

```bash
# A. Is it GROWING? (Leak)
# Compare: memory at 10:00 vs. 10:40

# B. Is it STABLE? (Normal, just at 85%)
# Look at graph: Is it flat or trending up?

# C. Get breakdown by component
# Flink Memory = JVM Heap + State Backend + Buffers
# JVM Heap (Java objects) = growing? = Leak
# State Backend (RocksDB) = growing? = State not cleaning up
# Buffers (network buffers) = growing? = Backpressure

# Check state size
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name StateBackendUsedBytes \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# If growing = state leak (window not clearing)
```

### Step 3: Fix Based on Cause

**A. Memory Leak (JVM Heap Growing)**
```bash
# 1. Take heap dump
kubectl exec -it flink-taskmanager-0 -- jmap -dump:live,format=b,file=heap.dump 1

# 2. Analyze with Eclipse MAT or jhat
jhat heap.dump

# 3. Look for growing object count:
# jhat output will show class with most instances
# E.g., "HashMap: 10M instances" = leak!

# 4. Common causes in Flink:
# - Local cache not clearing (add TTL)
# - Flink state not cleaning (check TTL config)
# - Window not emitting (check trigger)

# Fix: Add TTL to state
# File: KafkaStreamingJob.java
.window(TumblingEventTimeWindow.of(Time.minutes(5)))
 .trigger(EventTimeTrigger.create())
 .evictor(TimeEvictor.of(Time.minutes(5)))  # Clear old data
```

**B. State Backend Growing (RocksDB)**
```bash
# 1. Check state size
kubernetes exec -it flink-taskmanager-0 -- du -sh /tmp/flink-state*

# If > 5 GB = too large

# 2. Likely cause: Window never emitting
# Records accumulate in state
# Window size 5 min but records for 100 min in state = leak!

# Check window emit logs:
kubectl logs -l app=flink-taskmanager | grep "window emitted" | wc -l

# Should emit every 5 minutes

# Fix: Check window trigger
# File: KafkaStreamingJob.java
.window(TumblingEventTimeWindow.of(Time.minutes(5)))
 .trigger(EventTimeTrigger.create())  # Close window on event time
```

**C. Buffers Growing (Backpressure)**
```bash
# 1. Check buffer usage
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name task_buffer_out_pool_usage_percentage \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# If >80% = buffers full = downstream slow

# 2. Check downstream (Firehose)
# Is Firehose accepting data?
# See "Consumer Lag High" runbook
```

### Step 4: Immediate Mitigation

```bash
# Option 1: Increase memory (temporary, buy time for root cause fix)
kubectl set resources deployment flink-taskmanager \
  --limits memory=16Gi \
  --requests memory=8Gi

# Option 2: Increase GC frequency
# File: flink-config.yaml
env.java.opts: "-XX:+UseG1GC -XX:MaxGCPauseMillis=200"

# Option 3: Reduce state TTL (clear old data faster)
# File: KafkaStreamingJob.java
StateTtlConfig ttlConfig = StateTtlConfig
  .newBuilder(Time.seconds(3600))  # 1 hour instead of 24 hours
  .setUpdateType(StateTtlConfig.UpdateType.OnCreateAndWrite)
  .build();
```

### Step 5: Verify Fix

```bash
# 1. Monitor memory trend after fix
watch -n 60 'kubectl top pod -l app=flink-taskmanager | grep flink-taskmanager'

# Memory should stabilize or decrease

# 2. If leak: Monitor GC pauses (should increase, but memory decreases)
kubectl exec -it flink-taskmanager-0 -- jstat -gc 1 1000 | tail -10

# GC should free memory

# 3. Once stable, investigate root cause offline
# Don't just scale memory forever
```

---

## Checkpoint Duration High - MEDIUM

**Alert**: `checkpoint-duration-high` triggered (>30 seconds)

**Expected Impact**: Job pauses every checkpoint, customer latency spikes

**Time to Fix**: 5-20 minutes

### Step 1: Assess (1 min)

```bash
# 1. Check checkpoint duration trend
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name checkpoint_duration_ms \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# Example:
# 10:00 | 5000 ms (5 sec - normal)
# 10:10 | 8000 ms (8 sec - normal)
# 10:20 | 15000 ms (15 sec - slow)
# 10:30 | 32000 ms (32 sec - ALERT)

# Growing trend = checkpoint size growing

# 2. Get checkpoint size
aws logs start-query \
  --log-group-name ecommerce-streaming \
  --start-time $(date -d '1 hour ago' +%s) \
  --end-time $(date +%s) \
  --query-string '
    fields checkpoint_size_bytes
    | stats avg(checkpoint_size_bytes) as avg_bytes, max(checkpoint_size_bytes) as max_bytes
  '

# Example:
# avg_bytes: 500MB
# max_bytes: 2GB
# Taking 2GB * 8 Mbps = 250 sec = way too long!
```

### Step 2: Root Cause (2 min)

**A. Checkpoint Size Growing (State Leak)**
```bash
# 1. Check state backend size
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name StateBackendUsedBytes \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average

# If trending up = state not clearing

# Fix: Add window cleanup
# File: KafkaStreamingJob.java
.window(TumblingEventTimeWindow.of(Time.minutes(5)))
 .evictor(TimeEvictor.of(Time.minutes(5)))  # Discard old records
```

**B. Network Slow (S3 Slow Upload)**
```bash
# 1. Test S3 upload speed
dd if=/dev/zero bs=1M count=500 | time aws s3 cp - s3://checkpoint-bucket/test-file

# If > 30 seconds for 500 MB = network slow

# 2. Check S3 network latency
# Can we increase parallelism of checkpoint?
# File: flink-config.yaml
state.backend.rocksdb.thread.num: 4  # Parallel threads to S3

# 3. Or increase checkpoint timeout (accept slow checkpoints)
# File: KafkaStreamingJob.java
env.enableExternalizedCheckpoints(CheckpointConfig.ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION);
env.getCheckpointConfig().setCheckpointTimeout(600000);  # 10 minutes
```

**C. RocksDB Compaction Pause**
```bash
# 1. Check RocksDB logs
kubectl logs -l app=flink-taskmanager | grep -i compaction | tail -10

# RocksDB may be compacting during checkpoint = pause

# 2. Tuning options
# File: flink-config.yaml
state.backend.rocksdb.compaction.style: level
state.backend.rocksdb.compaction.trigger: 4
state.backend.rocksdb.compaction.options.style: universal
```

### Step 3: Fix

**If state growing:**
- Clear old state (evictor)
- Reduce TTL
- Increase window emit frequency

**If network slow:**
- Increase parallelism
- Use S3 Transfer Acceleration

**If RocksDB compacting:**
- Tune compaction style
- Accept slower checkpoints

### Step 4: Verify

```bash
# 1. Monitor checkpoint duration decreasing
watch -n 60 'aws cloudwatch get-metric-statistics --namespace ecommerce-streaming --metric-name checkpoint_duration_ms --start-time $(date -u -d "30 min ago" +%Y-%m-%dT%H:%M:%S) --end-time $(date -u +%Y-%m-%dT%H:%M:%S) --period 60 --statistics Average,Maximum | jq ".Datapoints[-3:]"'

# Should see duration dropping

# 2. Check latency spikes improving
# Latency should no longer spike every checkpoint
aws cloudwatch get-metric-statistics \
  --namespace ecommerce-streaming \
  --metric-name LatencyP99 \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 60 \
  --statistics Average
```

