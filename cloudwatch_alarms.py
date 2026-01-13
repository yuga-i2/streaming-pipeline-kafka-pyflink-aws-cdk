"""
CloudWatch alerting rules for PyFlink streaming pipeline.

Defines alarms with:
- Thresholds (SLO-based)
- Evaluation periods
- Actions (SNS, PagerDuty)
- Rationale for each threshold
"""

import json
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    CRITICAL = "CRITICAL"  # Page on-call immediately
    HIGH = "HIGH"          # Create ticket, monitor closely
    MEDIUM = "MEDIUM"      # Log, investigate during business hours
    LOW = "LOW"            # Log only


class AlertAction(str, Enum):
    """Alert actions."""
    PAGE_ONCALL = "arn:aws:sns:us-east-1:ACCOUNT:oncall-pager"
    SLACK_CRITICAL = "arn:aws:sns:us-east-1:ACCOUNT:slack-critical"
    SLACK_ALERTS = "arn:aws:sns:us-east-1:ACCOUNT:slack-alerts"
    EMAIL = "arn:aws:sns:us-east-1:ACCOUNT:ops-email"


@dataclass
class AlarmThreshold:
    """Single alarm configuration."""
    alarm_name: str
    metric_name: str
    namespace: str = "ecommerce-streaming"
    statistic: str = "Average"  # Average, Sum, Maximum, Minimum
    comparison_operator: str = "GreaterThanThreshold"  # GreaterThanThreshold, LessThanThreshold
    threshold: float = None
    evaluation_periods: int = 1  # How many periods to evaluate
    period_seconds: int = 60  # Period duration
    datapoints_to_alarm: int = 1  # How many datapoints must breach
    severity: AlertSeverity = AlertSeverity.MEDIUM
    actions: List[AlertAction] = None
    description: str = ""
    rationale: str = ""
    dimensions: Dict[str, str] = None
    treat_missing_data: str = "notBreaching"  # notBreaching, breaching, missing
    
    def __post_init__(self):
        if self.actions is None:
            self.actions = []
        if self.dimensions is None:
            self.dimensions = {}


# ============================================================================
# CRITICAL ALARMS (Page Immediately)
# ============================================================================

def get_dlq_spike_alarm() -> AlarmThreshold:
    """
    Alert: DLQ record rate exceeds 100 records/minute.
    
    Interpretation:
    - <10/min: Normal, occasional errors expected
    - 10-100/min: Yellow flag, investigate within 1 hour
    - >100/min: RED flag, something is wrong with data quality
    
    Root causes:
    - Source data schema changed (parse errors)
    - Upstream system sending bad data
    - Duplicate detection not working
    - Business logic bug
    
    Action:
    - Page on-call
    - Check DLQ reason breakdown in CloudWatch
    - Review latest code deployment
    """
    return AlarmThreshold(
        alarm_name="dlq-spike-critical",
        metric_name="DLQRecordCount",
        threshold=100,
        statistic="Sum",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=1,
        period_seconds=60,
        severity=AlertSeverity.CRITICAL,
        actions=[AlertAction.PAGE_ONCALL, AlertAction.SLACK_CRITICAL],
        description="DLQ rate >100 records/min indicates data quality issue",
        rationale="""
        DLQ (Dead Letter Queue) captures unparseable/invalid records.
        Rate >100/min means:
        1. 100 records/min failing to process = data loss risk
        2. Likely schema mismatch or validation failure
        3. Requires immediate investigation
        
        Previous incidents:
        - Jan 2025: Source API changed field type → 10K records in DLQ
        - Dec 2024: Duplicate check broken → 5K false duplicates per min
        
        Threshold rationale: 100/min = 6K/hour = probably automated, not one-off
        """
    )


def get_checkpoint_failure_alarm() -> AlarmThreshold:
    """
    Alert: Checkpoints failing (can't save state).
    
    Interpretation:
    - Checkpoint failure = Flink can't persist state
    - If job restarts, state is lost = potential data loss
    - Possible causes:
      - RocksDB disk full
      - S3 put permission denied
      - Network timeout to checkpoint storage
    
    Action:
    - Page on-call immediately
    - Check Flink logs for underlying cause
    - Verify S3 bucket is accessible
    """
    return AlarmThreshold(
        alarm_name="checkpoint-failure-critical",
        metric_name="checkpoint_failures_total",
        threshold=0,
        statistic="Sum",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=1,  # Alert immediately on first failure
        period_seconds=300,    # Check every 5 minutes
        severity=AlertSeverity.CRITICAL,
        actions=[AlertAction.PAGE_ONCALL, AlertAction.SLACK_CRITICAL],
        description="Checkpoint failure = state not persisted = restart would lose data",
        rationale="""
        Checkpoints are Flink's mechanism to save state (for recovery).
        If checkpoint fails:
        - Job continues but state is unrecoverable
        - On restart, job starts from last successful checkpoint
        - Any state changes since last checkpoint are lost
        
        Root causes:
        - S3 permission denied (IAM policy changed)
        - RocksDB disk full
        - Network timeout to checkpoint storage
        - Checkpoint too large (timeout)
        
        Threshold rationale: 0 failures expected in production. Any failure = page.
        """
    )


def get_kafka_broker_down_alarm() -> AlarmThreshold:
    """
    Alert: Kafka cluster has <3 brokers alive.
    
    In MSK Serverless (3 brokers minimum):
    - 3 brokers: Normal
    - 2 brokers: Already degraded, potential data loss if 1 more fails
    - <2 brokers: Cannot produce/consume
    
    Action:
    - Page infrastructure team
    - Check AWS MSK console for broker health
    """
    return AlarmThreshold(
        alarm_name="kafka-broker-down-critical",
        metric_name="kafka_broker_alive_count",
        threshold=3,
        statistic="Minimum",
        comparison_operator="LessThanThreshold",
        evaluation_periods=1,
        period_seconds=60,
        severity=AlertSeverity.CRITICAL,
        actions=[AlertAction.PAGE_ONCALL],
        description="Kafka cluster degraded: <3 brokers alive",
        rationale="""
        MSK Serverless uses 3 brokers for redundancy.
        - 3 brokers: Can lose 1 and still function
        - 2 brokers: Can lose 1 and still function, but approaching critical
        - <2 brokers: Cluster cannot function
        
        If <3:
        1. Cluster is already impaired
        2. Any further broker failure = total outage
        3. Need immediate investigation
        
        Threshold rationale: Alert at <3 (already degraded state)
        """
    )


def get_firehose_delivery_failure_alarm() -> AlarmThreshold:
    """
    Alert: Firehose failed to deliver to S3.
    
    Firehose has built-in retry, but failures indicate:
    - S3 bucket permission issue
    - S3 quota exceeded
    - S3 KMS key denied access
    
    Action:
    - Page on-call
    - Check Firehose delivery stream state
    - Verify IAM policy and S3 encryption key
    """
    return AlarmThreshold(
        alarm_name="firehose-delivery-failure-critical",
        metric_name="firehose_failed_put_count",
        threshold=0,
        statistic="Sum",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=1,
        period_seconds=60,
        severity=AlertSeverity.CRITICAL,
        actions=[AlertAction.PAGE_ONCALL, AlertAction.SLACK_CRITICAL],
        description="Firehose delivery to S3 failed = data not persisted",
        rationale="""
        Firehose's job: Buffer records and deliver to S3.
        Delivery failure means:
        - Records are buffered in Firehose (5 min max)
        - If not delivered in 5 min, records are lost
        - Before buffer full = urgent to fix
        
        Root causes:
        - S3 permission denied (missing s3:PutObject)
        - S3 KMS key denied (missing kms:Decrypt)
        - S3 quota exceeded (PutObject throttled)
        - S3 bucket doesn't exist
        
        Threshold: 0 failures expected. Any failure = page.
        """
    )


# ============================================================================
# HIGH PRIORITY ALARMS (Investigate within 1 hour)
# ============================================================================

def get_consumer_lag_alarm() -> AlarmThreshold:
    """
    Alert: Kafka consumer lag exceeds 50K records.
    
    Consumer lag = offset behind = how many records we haven't processed yet.
    
    Interpretation:
    - <10K: Normal, occasional bursts
    - 10-50K: Falling behind, need to investigate throughput
    - >50K: Significantly behind, need scaling or optimization
    
    Root causes:
    - Processing too slow (backpressure)
    - Enrichment API timeout
    - Window not clearing
    - Insufficient parallelism
    
    Action:
    - Alert (don't page, investigate during business hours)
    - Check Flink task manager logs
    - Monitor if lag keeps growing
    """
    return AlarmThreshold(
        alarm_name="kafka-consumer-lag-high",
        metric_name="consumer_lag_records",
        threshold=50000,
        statistic="Maximum",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=2,  # Alert if >50K for 2 consecutive periods
        period_seconds=60,
        severity=AlertSeverity.HIGH,
        actions=[AlertAction.SLACK_ALERTS, AlertAction.EMAIL],
        description="Consumer lag >50K records = falling behind producer",
        rationale="""
        Consumer lag = messages we haven't processed yet = backlog.
        
        Why it matters:
        - Lag = latency delay (dashboard data stale by X minutes)
        - Growing lag = we're slower than producer = will eventually overflow
        - Stable lag = we're keeping up (good)
        
        Baseline expectations:
        - During peak hours: Lag can spike to 10-20K (temporary)
        - Off-peak: Lag should be <1K
        - Alert threshold: 50K (means we've been slow for >5 min)
        
        Investigation steps:
        1. Check Flink throughput (records/sec in vs. out)
        2. Check CPU/memory usage on task managers
        3. Check enrichment API latency (if >1 sec, that's the bottleneck)
        4. Check window emit frequency
        """
    )


def get_processing_latency_slo_alarm() -> AlarmThreshold:
    """
    Alert: P99 latency exceeds 5 seconds (SLO breach).
    
    SLO (Service Level Objective):
    - p50: <2 seconds (50% of orders complete in <2s)
    - p95: <3 seconds (95% of orders complete in <3s)
    - p99: <5 seconds (99% of orders complete in <5s)
    
    If p99 > 5s, we're breaching SLO for 1% of customers.
    
    Root causes:
    - Backpressure (Flink slower than input)
    - GC pause (Java garbage collection)
    - External API timeout (enrichment)
    - Kafka lag (waiting for data)
    
    Action:
    - Monitor closely
    - Check Flink logs for slowness indicators
    - May need to scale up task managers
    """
    return AlarmThreshold(
        alarm_name="processing-latency-slo-breach",
        metric_name="LatencyP99",
        threshold=5000,  # milliseconds
        statistic="Average",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=2,
        period_seconds=60,
        severity=AlertSeverity.HIGH,
        actions=[AlertAction.SLACK_ALERTS],
        description="P99 latency >5s = SLO breach for 1% of customers",
        rationale="""
        Processing latency = time from order ingestion to result output.
        
        SLOs (from product team):
        - p50: <2 sec (typical case)
        - p95: <3 sec (most cases)
        - p99: <5 sec (worst 1%)
        
        If p99 > 5s:
        - 1% of customers see stale data
        - Real-time personalization fails
        - Customer dashboards lag
        
        Typical latency breakdown:
        - Deserialization: 10 ms
        - Validation: 20 ms
        - Enrichment (API call): 200-500 ms (can spike)
        - Window aggregation: 100-2000 ms (depends on window size)
        - S3 delivery: <100 ms
        Total: 300-2600 ms typically
        
        If >5s, usually:
        1. Enrichment API is slow (timeout or slow response)
        2. Backpressure (downstream full)
        3. GC pause (check JVM metrics)
        """
    )


def get_window_completeness_alarm() -> AlarmThreshold:
    """
    Alert: Window completeness <95%.
    
    Window completeness = (records emitted) / (records entered) * 100.
    
    <95% means:
    - 5%+ of records are not making it through window
    - Could be late arrivals (expected) or data loss (bad)
    
    Root causes:
    - Late arriving data (beyond allowed lateness window)
    - Watermark stuck (not advancing)
    - Window state corruption
    - Out-of-order records
    
    Action:
    - Investigate immediately
    - Check watermark lag metric
    - Review late arrival count
    """
    return AlarmThreshold(
        alarm_name="window-completeness-low",
        metric_name="WindowCompleteness",
        threshold=95.0,  # percent
        statistic="Average",
        comparison_operator="LessThanThreshold",
        evaluation_periods=1,
        period_seconds=300,  # Check every 5 minutes
        severity=AlertSeverity.HIGH,
        actions=[AlertAction.SLACK_CRITICAL, AlertAction.PAGE_ONCALL],
        description="Window completeness <95% = potential data loss",
        rationale="""
        Window completeness = data making it through the window operation.
        
        Formula: completeness = (records_emitted / records_entered) * 100
        
        100% = all records made it through
        99% = 1% lost (bad!)
        95% = 5% lost (critical!)
        
        Why it drops:
        1. Late arrivals (data arrives after window closes)
           - Expected with out-of-order data
           - Mitigation: allowedLateness(Duration.minutes(5))
        2. Watermark stuck (window never closes)
           - Indicates upstream issue
           - Watermark should advance every few seconds
        3. State backend issue (dropped records)
           - Indicates data loss bug
           - Requires investigation
        4. Config issue (window size too small)
           - If window is 5 sec but data arrives in 10 sec, loss expected
        
        Threshold: 95% minimum. Anything lower = investigate.
        """
    )


# ============================================================================
# MEDIUM PRIORITY ALARMS (Check during business hours)
# ============================================================================

def get_memory_usage_alarm() -> AlarmThreshold:
    """
    Alert: Heap memory usage >85%.
    
    High memory usage can indicate:
    - Memory leak (growing over time)
    - State backend growing (unbounded state)
    - Buffer accumulation (backpressure)
    
    Threshold 85% = still have headroom, but trending dangerously.
    
    Action:
    - Monitor trend (is it growing?)
    - Check for memory leak
    - May need to scale up or optimize
    """
    return AlarmThreshold(
        alarm_name="memory-usage-high",
        metric_name="memory_usage_percentage",
        threshold=85.0,
        statistic="Average",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=2,
        period_seconds=60,
        severity=AlertSeverity.MEDIUM,
        actions=[AlertAction.SLACK_ALERTS],
        description="Heap memory >85% = potential OOM risk",
        rationale="""
        JVM heap memory usage >85% indicates:
        1. Approaching capacity (OOMKill risk)
        2. Potential memory leak (if growing over hours)
        3. Backpressure (buffers full)
        
        What to check:
        - Is it stable or growing? (trend)
        - Does it spike with heavy load? (normal)
        - Does it leak after load drops? (bad, indicates leak)
        
        JVM GC will attempt to free memory before OOM.
        If GC can't free enough, task manager crashes.
        
        Threshold: 85% gives headroom for GC to work.
        """
    )


def get_checkpoint_duration_alarm() -> AlarmThreshold:
    """
    Alert: Checkpoint takes >30 seconds.
    
    Checkpoints should be fast (<10 sec typically).
    >30 seconds indicates:
    - Checkpoint is too large (state backend bloat)
    - Network slow (S3 upload slow)
    - State lock contention (many threads competing)
    
    Long checkpoints cause backpressure (job pauses during checkpoint).
    
    Action:
    - Investigate checkpoint size
    - Check S3 network latency
    - May need to optimize state backend
    """
    return AlarmThreshold(
        alarm_name="checkpoint-duration-high",
        metric_name="checkpoint_duration_ms",
        threshold=30000,  # milliseconds
        statistic="Average",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=2,
        period_seconds=60,
        severity=AlertSeverity.MEDIUM,
        actions=[AlertAction.SLACK_ALERTS],
        description="Checkpoint >30s = excessive pause, likely state bloat",
        rationale="""
        Checkpoint = save state to disk/S3 for recovery.
        
        Timing:
        - Normal: 5-10 seconds
        - Slow: 10-30 seconds (investigate)
        - Excessive: >30 seconds (state too large or network slow)
        
        Long checkpoints cause:
        - Job pauses during checkpoint (no records processed)
        - Lag increases (buffers fill up)
        - Customers see latency spike
        
        Typical checkpoint sizes:
        - Small pipeline: 100 MB → <5 sec
        - Medium pipeline: 1 GB → 10-15 sec
        - Large pipeline: 10+ GB → >30 sec (needs attention)
        
        If growing over time = state leak (not cleaning up old data).
        """
    )


def get_duplicate_detection_spike_alarm() -> AlarmThreshold:
    """
    Alert: Duplicate detection rate >10 per minute.
    
    Duplicate detection counts records we've already seen.
    Spike in duplicates indicates:
    - Source is re-sending data
    - Network retries causing duplication
    - Deduplication window too small
    
    Action:
    - Monitor source system
    - Check if intentional (source retry)
    - May need to extend dedup window
    """
    return AlarmThreshold(
        alarm_name="duplicate-detection-spike",
        metric_name="DuplicateRecordDetected",
        threshold=10,
        statistic="Sum",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=1,
        period_seconds=60,
        severity=AlertSeverity.MEDIUM,
        actions=[AlertAction.SLACK_ALERTS],
        description="Duplicate detection >10/min = source sending duplicates",
        rationale="""
        Deduplication = detecting and removing duplicate records.
        
        Normal rate: <1 duplicate per minute (occasional retries)
        High rate: >10 per minute (systematic problem)
        
        Root causes:
        - Source API is retrying (network flake)
        - Kafka consumer reset (processing messages again)
        - Load balancer duplicating traffic
        - Dedup window too small (time window expired)
        
        Why it matters:
        - Each duplicate = wasted processing
        - If dedup window expires = duplicate passes through
        - Customers see duplicate charges/orders
        
        Threshold: 10/min = systematic, not one-off.
        """
    )


# ============================================================================
# LOW PRIORITY ALARMS (Log only, no page)
# ============================================================================

def get_kafka_deserialization_error_alarm() -> AlarmThreshold:
    """
    Alert: JSON deserialization errors >5 per minute.
    
    Deserialization errors = Kafka message isn't valid JSON.
    Low rate (<5/min) is expected (occasional bad messages).
    Higher rate indicates:
    - Source schema changed
    - Source system bug
    
    Action:
    - Log to monitoring dashboard
    - Investigate during business hours
    """
    return AlarmThreshold(
        alarm_name="deserialization-error-low",
        metric_name="kafka_deserialization_errors_total",
        threshold=5,
        statistic="Sum",
        comparison_operator="GreaterThanThreshold",
        evaluation_periods=1,
        period_seconds=60,
        severity=AlertSeverity.LOW,
        actions=[AlertAction.EMAIL],
        description="Deserialization errors >5/min = malformed messages",
        rationale="""
        Deserialization = parsing Kafka message from JSON to object.
        Errors = message isn't valid JSON or missing required fields.
        
        Normal rate: <1 per 10 minutes (occasional bad data)
        Concerning: >5 per minute (systematic issue)
        
        Usually indicates:
        - Source API changed JSON schema (missing field)
        - Source has bug (bad encoding)
        - Network corruption (unlikely, Kafka has checksums)
        
        These messages end up in DLQ (already tracked by DLQ alarm).
        This alarm just tracks deserialization specifically.
        """
    )


# ============================================================================
# Alarm Summary & Configuration
# ============================================================================

def get_all_alarms() -> List[AlarmThreshold]:
    """Return all configured alarms."""
    return [
        # CRITICAL
        get_dlq_spike_alarm(),
        get_checkpoint_failure_alarm(),
        get_kafka_broker_down_alarm(),
        get_firehose_delivery_failure_alarm(),
        
        # HIGH
        get_consumer_lag_alarm(),
        get_processing_latency_slo_alarm(),
        get_window_completeness_alarm(),
        
        # MEDIUM
        get_memory_usage_alarm(),
        get_checkpoint_duration_alarm(),
        get_duplicate_detection_spike_alarm(),
        
        # LOW
        get_kafka_deserialization_error_alarm(),
    ]


def print_alarm_summary():
    """Print all alarms in table format."""
    print("\n" + "=" * 120)
    print("CLOUDWATCH ALARM CONFIGURATION")
    print("=" * 120)
    
    alarms_by_severity = {}
    for alarm in get_all_alarms():
        severity = alarm.severity.value
        if severity not in alarms_by_severity:
            alarms_by_severity[severity] = []
        alarms_by_severity[severity].append(alarm)
    
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        if severity in alarms_by_severity:
            print(f"\n{severity} ALARMS ({len(alarms_by_severity[severity])})")
            print("-" * 120)
            
            for alarm in alarms_by_severity[severity]:
                print(f"\n{alarm.alarm_name}")
                print(f"  Metric: {alarm.metric_name}")
                print(f"  Threshold: {alarm.comparison_operator} {alarm.threshold}")
                print(f"  Description: {alarm.description}")
                print(f"  Rationale: {alarm.rationale[:200]}...")


def export_alarms_as_cloudformation(output_file: str = "alarms.json"):
    """Export all alarms as CloudFormation template."""
    resources = {}
    
    for alarm in get_all_alarms():
        resource_name = alarm.alarm_name.replace("-", "")
        
        alarm_actions = [action.value for action in alarm.actions]
        
        dimensions = [
            {"Name": key, "Value": value}
            for key, value in alarm.dimensions.items()
        ] if alarm.dimensions else []
        
        resources[f"Alarm{resource_name}"] = {
            "Type": "AWS::CloudWatch::Alarm",
            "Properties": {
                "AlarmName": alarm.alarm_name,
                "AlarmDescription": alarm.description,
                "MetricName": alarm.metric_name,
                "Namespace": alarm.namespace,
                "Statistic": alarm.statistic,
                "Period": alarm.period_seconds,
                "EvaluationPeriods": alarm.evaluation_periods,
                "DatapointsToAlarm": alarm.datapoints_to_alarm,
                "Threshold": alarm.threshold,
                "ComparisonOperator": alarm.comparison_operator,
                "Dimensions": dimensions,
                "TreatMissingData": alarm.treat_missing_data,
                "AlarmActions": alarm_actions,
                "Tags": [
                    {"Key": "Environment", "Value": "production"},
                    {"Key": "Pipeline", "Value": "order-processing"},
                ]
            }
        }
    
    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "CloudWatch alarms for ecommerce streaming pipeline",
        "Resources": resources
    }
    
    with open(output_file, "w") as f:
        json.dump(template, f, indent=2)
    
    print(f"\nExported CloudFormation template: {output_file}")


if __name__ == "__main__":
    print_alarm_summary()
    export_alarms_as_cloudformation()
