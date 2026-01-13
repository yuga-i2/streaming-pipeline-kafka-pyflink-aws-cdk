# DEPLOYMENT.md

**Complete step-by-step guide to deploy, configure, and operate the streaming pipeline.**

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Development Environment](#development-environment)
4. [AWS Account Configuration](#aws-account-configuration)
5. [CDK Deployment](#cdk-deployment)
6. [Verification](#verification)
7. [Security Configuration](#security-configuration)
8. [Production Deployment](#production-deployment)
9. [Monitoring & Alerts](#monitoring--alerts)
10. [Troubleshooting](#troubleshooting)
11. [Cost Optimization](#cost-optimization)
12. [Cleanup](#cleanup)

---

## Prerequisites

### Required
- **AWS Account** with `AdministratorAccess` or equivalent permissions
- **AWS CLI v2** (`aws --version` should show 2.x+)
- **Python 3.8+** (`python3 --version`)
- **Node.js 14+** (`npm --version`)
- **Git** (`git --version`)
- **Docker** (for local testing, optional)

### Recommended
- **AWS credentials configured** (`aws configure`)
- **VS Code** with Python extension
- **Postman** (for API testing)

### Verify Setup

```bash
# Check prerequisites
aws --version                    # v2.x+
python3 --version              # 3.8+
npm --version                  # 14+
node --version                 # 14+

# Configure AWS credentials (if not done)
aws configure                   # Enter access key, secret, region, format
aws sts get-caller-identity     # Verify credentials work

# Install CDK
npm install -g aws-cdk@2.60.0
cdk --version                  # Should show 2.60.0+
```

---

## Initial Setup

### 1. Clone Repository

```bash
git clone https://github.com/YOUR_ORG/streaming-pipeline-kafka-flink-firehose-s3-cdk.git
cd streaming-pipeline-kafka-flink-firehose-s3-cdk
git checkout main
```

### 2. Create Python Virtual Environment

```bash
# Create venv
python3 -m venv .venv

# Activate venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Verify activation (should show (.venv) prefix)
which python3
```

### 3. Install Python Dependencies

```bash
# Install CDK dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Verify installation
python3 -c "import aws_cdk; print(aws_cdk.VERSION)"  # Should show 2.60.0
```

### 4. Update Configuration

**Critical**: Update the S3 bucket name (must be globally unique):

```bash
# Edit project_config.json
nano project_config.json  # or use your editor

# Change:
{
  "flink": {
    "artifact_bucket_name": "YOUR_UNIQUE_BUCKET_NAME"  # e.g., "streaming-pipeline-artifacts-12345"
  }
}

# Bucket naming rules:
# - Lowercase letters, numbers, hyphens only
# - Must be unique across entire AWS (not just your account)
# - 3-63 characters
# - Recommended: "streaming-pipeline-artifacts-{organization}-{random}"

# Example:
#  "artifact_bucket_name": "streaming-pipeline-artifacts-acme-4567"
```

**Optional**: Customize other settings:

```json
{
  "region": "us-east-1",              // AWS region
  "environment": "dev",                // dev/staging/prod
  "flink": {
    "parallelism": 2,                 // Number of parallel tasks (start low)
    "checkpoint_interval_ms": 10000,  // Checkpoint frequency
    "artifact_bucket_name": "YOUR_UNIQUE_BUCKET"
  },
  "kafka": {
    "broker_count": 2,                // Number of Kafka brokers
    "instance_type": "kafka.m5.large" // Broker instance size
  }
}
```

---

## Development Environment

### Run Unit Tests

```bash
# Run all tests
pytest tests/unit/ -v

# Run specific test
pytest tests/unit/test_streaming_pipeline_kafka_flink_firehose_s3_cdk_stack.py::test_stack_can_be_synthesized -v

# Expected output: All tests pass (5-10 tests)
```

### Synthesize CDK Template

```bash
# Generate CloudFormation template (no deployment yet)
cdk synth

# Output: cdk.out/StreamingPipelineStack.template.json (CloudFormation template)

# View generated resources
cdk synth | grep "Type::" | head -20

# Expected: 50+ AWS resources defined
```

### View Stack Diff

```bash
# See what would change
cdk diff

# First deployment shows all new resources
# Subsequent deployments show only changes
```

---

## AWS Account Configuration

### 1. Verify Region

```bash
# Check configured region
aws configure get region

# Set region if not set
export AWS_REGION=us-east-1

# Verify
aws ec2 describe-availability-zones | head -20
```

### 2. Create KMS Key for Encryption

```bash
# Create KMS key for Kafka encryption
aws kms create-key \
  --description "Streaming Pipeline Kafka Encryption" \
  --origin AWS_KMS \
  --region us-east-1

# Note the KeyId (needed in next step)

# Create alias for easy reference
aws kms create-alias \
  --alias-name alias/streaming-pipeline-kafka \
  --target-key-id arn:aws:kms:us-east-1:ACCOUNT_ID:key/KEY_ID

# Verify
aws kms list-aliases | grep streaming-pipeline
```

### 3. Create CloudFormation Service Role (Optional, for additional security)

```bash
# Create role for CloudFormation
aws iam create-role \
  --role-name StreamingPipelineCDKRole \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "cloudformation.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach policy (allowing needed permissions)
aws iam attach-role-policy \
  --role-name StreamingPipelineCDKRole \
  --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
```

### 4. Check Service Quotas

```bash
# Check if you have quota to create resources
aws service-quotas get-service-quota \
  --service-code msk \
  --quota-code L-9382CCAE \
  --region us-east-1

# If quota is low (< 3), request increase
aws service-quotas request-service-quota-increase \
  --service-code msk \
  --quota-code L-9382CCAE \
  --desired-value 5
```

---

## CDK Deployment

### 1. Bootstrap CDK (First Time Only)

```bash
# Prepare AWS account for CDK
cdk bootstrap

# What this does:
# - Creates S3 bucket for CDK assets
# - Creates IAM role for CDK
# - Enables CloudFormation to deploy resources

# Expected output:
# ✓ Environment bootstrapped.
```

### 2. Deploy Dev Environment

```bash
# Deploy all stacks
cdk deploy --all --require-approval never

# Or deploy stacks individually (for debugging)
cdk deploy MSKServerlessStack --require-approval never
cdk deploy FlinkStack --require-approval never
cdk deploy FirehoseToS3Stack --require-approval never
cdk deploy SMFeatureStoreStack --require-approval never

# Expected duration: 15-25 minutes (depends on Kafka cluster provisioning)

# Output: Stack outputs (Kafka endpoints, S3 buckets, etc.)
```

### 3. Capture Stack Outputs

```bash
# Get all stack outputs
aws cloudformation describe-stacks \
  --query 'Stacks[*].Outputs' \
  --output table

# Key outputs to save:
# - KafkaBootstrapServers (endpoint for Kafka)
# - InputTopicName (e.g., input_topic)
# - OutputTopicName (e.g., output_topic)
# - DataLakeBucket (S3 bucket for data)
# - FeatureGroupName (SageMaker feature group)

# Store in env file for later
cat > .env.local << 'EOF'
export KAFKA_BOOTSTRAP_SERVERS=$(aws cloudformation describe-stacks --query 'Stacks[0].Outputs[?OutputKey==`KafkaBootstrapServers`].OutputValue' --output text)
export KAFKA_INPUT_TOPIC=$(aws cloudformation describe-stacks --query 'Stacks[0].Outputs[?OutputKey==`InputTopicName`].OutputValue' --output text)
export KAFKA_OUTPUT_TOPIC=$(aws cloudformation describe-stacks --query 'Stacks[0].Outputs[?OutputKey==`OutputTopicName`].OutputValue' --output text)
export DATA_LAKE_BUCKET=$(aws cloudformation describe-stacks --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' --output text)
export FEATURE_GROUP_NAME=$(aws cloudformation describe-stacks --query 'Stacks[0].Outputs[?OutputKey==`FeatureGroupName`].OutputValue' --output text)
EOF

source .env.local
echo "Kafka Bootstrap: $KAFKA_BOOTSTRAP_SERVERS"
```

---

## Verification

### 1. Verify Kafka Cluster

```bash
# Connect to bastion host (check EC2 console for IP)
export BASTION_IP=<IP_FROM_EC2_CONSOLE>
ssh -i /path/to/key.pem ec2-user@$BASTION_IP

# From bastion, check Kafka
kafka-topics.sh --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS --list

# Expected output:
# dlq_topic
# input_topic
# output_topic
```

### 2. Verify Flink Application

```bash
# Check Flink job status
aws kinesis-video-webrtc describe-signaling-channel \
  --region us-east-1

# Better: Check CloudWatch Logs
aws logs tail /aws/managed-flink/ApplicationName --follow

# Should see: "Starting PyFlink Application" and no errors
```

### 3. Verify Lambda Functions

```bash
# List deployed Lambdas
aws lambda list-functions --query 'Functions[?contains(FunctionName, `streaming`) || contains(FunctionName, `producer`)]' --output table

# Test producer Lambda
aws lambda invoke \
  --function-name streaming-pipeline-producer \
  --payload '{}' \
  response.json

# Check response
cat response.json

# Check logs
aws logs tail /aws/lambda/streaming-pipeline-producer --follow --since 1m
```

### 4. Verify S3 Buckets

```bash
# List S3 buckets for this pipeline
aws s3 ls | grep streaming-pipeline

# Check data lake bucket
aws s3 ls s3://$DATA_LAKE_BUCKET/

# Expected: No data yet (Firehose will create structure when it delivers)
```

### 5. Verify SageMaker Feature Store

```bash
# Check feature group
aws sagemaker describe-feature-group \
  --feature-group-name $FEATURE_GROUP_NAME

# List records (may be empty if no data yet)
aws sagemaker-featurestore-runtime get-record \
  --feature-group-name $FEATURE_GROUP_NAME \
  --record-identifier-value-as-string "AMZN"
```

---

## Security Configuration

### 1. VPC Security Group Rules

```bash
# Get security group IDs
aws ec2 describe-security-groups \
  --query 'SecurityGroups[?contains(GroupName, `streaming`)].GroupId' \
  --output text

# Check inbound rules (should be very restricted)
aws ec2 describe-security-group-rules \
  --filters "Name=group-id,Values=sg-xxxxxxxx" \
  --output table

# Verify:
# - Kafka: Only from Flink security group (not 0.0.0.0)
# - Bastion: Only from your IP (not 0.0.0.0)
# - Flink: Only from ALB (if exposed)
```

### 2. IAM Roles & Policies

```bash
# Check Flink execution role
aws iam get-role \
  --role-name streaming-pipeline-flink-role

# Check attached policies
aws iam list-attached-role-policies \
  --role-name streaming-pipeline-flink-role

# Verify policies follow least-privilege principle:
# - Kafka: Only read input_topic, write output_topic/dlq_topic
# - S3: Only read/write to checkpoints and data lake
# - CloudWatch: Only put metrics and logs
# - Denied: Anything else
```

### 3. Enable Encryption

```bash
# Verify S3 encryption
aws s3api get-bucket-encryption \
  --bucket $DATA_LAKE_BUCKET

# Expected: KMS key for encryption

# Verify Kafka encryption
aws msk describe-cluster \
  --cluster-arn arn:aws:msk:REGION:ACCOUNT:cluster/NAME/ID \
  --output table

# Look for: "EncryptionInfo" with KMS key
```

### 4. Enable VPC Flow Logs

```bash
# Get VPC ID
export VPC_ID=$(aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=streaming-pipeline*" \
  --query 'Vpcs[0].VpcId' \
  --output text)

# Create CloudWatch log group
aws logs create-log-group \
  --log-group-name /aws/vpc/streaming-pipeline

# Enable flow logs
aws ec2 create-flow-logs \
  --resource-type VPC \
  --resource-ids $VPC_ID \
  --traffic-type ALL \
  --log-destination-type cloud-watch-logs \
  --log-group-name /aws/vpc/streaming-pipeline \
  --deliver-logs-permission-role arn:aws:iam::ACCOUNT_ID:role/vpc-flow-logs-role
```

### 5. Enable CloudTrail Logging

```bash
# Create S3 bucket for CloudTrail logs
aws s3api create-bucket \
  --bucket streaming-pipeline-cloudtrail-logs \
  --region us-east-1

# Create CloudTrail
aws cloudtrail create-trail \
  --name streaming-pipeline-trail \
  --s3-bucket-name streaming-pipeline-cloudtrail-logs

# Start logging
aws cloudtrail start-logging \
  --trail-name streaming-pipeline-trail
```

---

## Production Deployment

### 1. Staging Environment Setup

```bash
# Create staging config
cp config/dev.json config/staging.json

# Edit for staging
nano config/staging.json

# Key differences:
{
  "environment": "staging",
  "flink": {
    "parallelism": 4,                    // More than dev
    "checkpoint_interval_ms": 5000,      // More frequent
    "artifact_bucket_name": "streaming-pipeline-artifacts-staging"
  },
  "kafka": {
    "broker_count": 3,                   // Production-like
    "instance_type": "kafka.m5.xlarge"   // Larger
  }
}

# Deploy staging
cdk deploy --all --context env=staging --require-approval never
```

### 2. Production Environment Setup

```bash
# Create production config
cp config/staging.json config/prod.json

# Edit for production
nano config/prod.json

# Key production settings:
{
  "environment": "prod",
  "flink": {
    "parallelism": 8,                    // High parallelism
    "checkpoint_interval_ms": 10000,     // Balanced
    "artifact_bucket_name": "streaming-pipeline-artifacts-prod"
  },
  "kafka": {
    "broker_count": 3,                   // Multi-AZ
    "instance_type": "kafka.m5.xlarge",  // Larger instances
    "retention_days": 14                 // Longer retention
  },
  "firehose": {
    "buffer_size_mb": 256,               // Larger buffers
    "buffer_time_seconds": 60,           // Time-based flush
    "compression": "GZIP"                // Compression
  }
}

# Deploy production (with approval)
cdk deploy --all --context env=prod --require-approval always
```

### 3. Blue-Green Deployment (Flink Job Updates)

```bash
# Deploy v2 of Flink job alongside v1
# This allows switching traffic without data loss

# Create savepoint from v1 (snapshot of state)
aws flink create-application-snapshot \
  --application-name streaming-pipeline \
  --snapshot-name v1-checkpoint-before-upgrade

# Deploy v2 as new application (with same Kafka topics)
cdk deploy FlinkStack --context version=v2

# Verify v2 is catching up (check consumer lag)
aws cloudwatch get-metric-statistics \
  --namespace StreamingPipeline \
  --metric-name consumer_lag_records \
  --start-time 2026-01-13T00:00:00Z \
  --end-time 2026-01-13T01:00:00Z \
  --period 60 \
  --statistics Average

# Once lag is caught up, stop v1
aws flink stop-application --application-name streaming-pipeline-v1

# Cleanup v1 infrastructure
cdk destroy StreamingPipelineStack:v1
```

### 4. Scaling Production

```bash
# Increase Flink parallelism
aws kinesis update-application \
  --application-name streaming-pipeline \
  --desired-parallelism 16

# Increase Kafka brokers
aws msk update-broker-count \
  --cluster-arn arn:aws:msk:REGION:ACCOUNT:cluster/NAME/ID \
  --desired-broker-count 6

# Increase Firehose buffer size
aws firehose update-delivery-stream \
  --delivery-stream-name streaming-pipeline-firehose \
  --extended-s3-destination-update ...

# Check scaling progress
aws cloudformation describe-stack-events \
  --stack-name StreamingPipelineStack
```

---

## Monitoring & Alerts

### 1. CloudWatch Dashboards

```bash
# Deploy dashboards (created by CDK)
# Check CloudWatch console: Dashboards > StreamingPipeline

# Dashboards available:
# - Health (5 golden signals)
# - Performance (latency, throughput)
# - Errors (DLQ, failures)
# - Capacity (scaling metrics)

# Or create manually:
aws cloudwatch put-dashboard \
  --dashboard-name StreamingPipelineHealth \
  --dashboard-body file://dashboards/health.json
```

### 2. CloudWatch Alarms

```bash
# List all alarms for this pipeline
aws cloudwatch describe-alarms \
  --query 'MetricAlarms[?contains(AlarmName, `streaming`)]' \
  --output table

# Expected: 11 alarms (4 CRITICAL, 3 HIGH, 2 MEDIUM, 2 LOW)

# Check alarm status
aws cloudwatch describe-alarms \
  --alarm-names StreamingPipelineDLQSpike \
  --output table

# Manually test alarm (if needed)
aws cloudwatch set-alarm-state \
  --alarm-name StreamingPipelineDLQSpike \
  --state-value ALARM \
  --state-reason "Testing alarm"
```

### 3. SNS Notifications

```bash
# Create SNS topic for alerts
aws sns create-topic \
  --name streaming-pipeline-alerts

# Get topic ARN
export TOPIC_ARN=$(aws sns list-topics \
  --query 'Topics[?contains(TopicArn, `streaming-pipeline-alerts`)].TopicArn' \
  --output text)

# Subscribe email
aws sns subscribe \
  --topic-arn $TOPIC_ARN \
  --protocol email \
  --notification-endpoint "your-email@example.com"

# Confirm subscription (check email)

# Add topic to alarms (done by CDK, but verify)
aws cloudwatch put-metric-alarm \
  --alarm-name StreamingPipelineDLQSpike \
  --alarm-actions $TOPIC_ARN
```

### 4. PagerDuty Integration (Optional)

```bash
# Create PagerDuty service integration key

# Create SNS topic for PagerDuty
aws sns create-topic \
  --name streaming-pipeline-pagerduty

# Subscribe PagerDuty webhook
aws sns subscribe \
  --topic-arn arn:aws:sns:REGION:ACCOUNT:streaming-pipeline-pagerduty \
  --protocol https \
  --notification-endpoint "https://events.pagerduty.com/v2/enqueue"

# Link alarms to PagerDuty
aws cloudwatch put-metric-alarm \
  --alarm-name StreamingPipelineCRITICAL \
  --alarm-actions arn:aws:sns:REGION:ACCOUNT:streaming-pipeline-pagerduty
```

---

## Troubleshooting

### Flink Job Not Starting

```bash
# Check Flink logs
aws logs tail /aws/kinesis-analytics/StreamingPipelineJob --follow

# Look for error messages (InvalidArgumentException, etc.)

# Check IAM role (common issue)
aws iam get-role-policy \
  --role-name flink-execution-role \
  --policy-name flink-policy

# Common fixes:
# 1. Verify Kafka security group allows Flink access
# 2. Verify IAM role has read access to Kafka topics
# 3. Verify state backend S3 bucket exists and is accessible
# 4. Verify Kafka topics exist (check with kafkacat)
```

### High Consumer Lag

```bash
# Check current lag
aws cloudwatch get-metric-statistics \
  --namespace StreamingPipeline \
  --metric-name consumer_lag_records \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average,Maximum

# Check Flink parallelism
aws kinesis describe-application \
  --application-name StreamingPipelineJob \
  | grep -i parallelism

# Increase parallelism
aws kinesis update-application \
  --application-name StreamingPipelineJob \
  --desired-parallelism 16

# Check if specific operator is slow
aws logs tail /aws/kinesis-analytics/StreamingPipelineJob \
  --filter-pattern "operator_latency" \
  --follow

# If enrichment is slow:
# 1. Check enrichment data size (may need caching)
# 2. Check enrichment API latency (external dependency)
# 3. Consider pre-loading enrichment data into memory
```

### DLQ Spike

```bash
# Check DLQ topic
kafka-console-consumer.sh \
  --bootstrap-server $KAFKA_BOOTSTRAP_SERVERS \
  --topic dlq_topic \
  --from-beginning \
  --max-messages 10

# Parse errors
aws logs tail /aws/kinesis-analytics/StreamingPipelineJob \
  --filter-pattern "error_type" \
  --follow

# Common causes:
# 1. Schema change (Kafka event structure changed)
#    → Update validation in order_processor.py
# 2. Invalid data from source (bad event)
#    → Fix source or add lenient parsing
# 3. Network timeout (enrichment API slow)
#    → Increase timeout, add retry logic
# 4. Duplicate detection triggered
#    → Check if this is expected behavior

# Fix and replay from DLQ
# 1. Fix the issue
# 2. Redeploy Flink job (new version)
# 3. Replay DLQ events (using utility)
```

### Firehose Not Delivering to S3

```bash
# Check Firehose delivery stream
aws firehose describe-delivery-stream \
  --delivery-stream-name streaming-pipeline-firehose

# Check delivery stream status
aws cloudwatch get-metric-statistics \
  --namespace AWS/Firehose \
  --metric-name DeliveryToS3.Records \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Sum

# Check S3 for failed deliveries
aws s3 ls s3://$DATA_LAKE_BUCKET/failed/

# Common causes:
# 1. S3 bucket doesn't exist
#    → Check bucket exists and is accessible
# 2. S3 permission denied
#    → Check IAM role has s3:PutObject permission
# 3. KMS key not accessible
#    → Check KMS key permissions
# 4. S3 quota exceeded
#    → Check S3 bucket size, request quota increase

# Re-enable delivery (if paused)
aws firehose put-record \
  --delivery-stream-name streaming-pipeline-firehose \
  --record Data="test"
```

### High Memory Usage

```bash
# Check memory usage
aws cloudwatch get-metric-statistics \
  --namespace StreamingPipeline \
  --metric-name jvm_memory_used_percent \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 \
  --statistics Average,Maximum

# Check for memory leak
aws logs tail /aws/kinesis-analytics/StreamingPipelineJob \
  --filter-pattern "OutOfMemory" \
  --follow

# Common causes:
# 1. State backend size growing (unbounded state)
#    → Add TTL to state (remove old data)
# 2. Buffered aggregations not flushed
#    → Check window configuration
# 3. Task manager heap too small
#    → Increase JVM heap (in flink configuration)

# Temporary fix
aws kinesis update-application \
  --application-name StreamingPipelineJob \
  --configuration-update "{\"EnvironmentProperties\": {\"JVM_OPTS\": \"-Xmx4g\"}}"
```

---

## Cost Optimization

### 1. Estimate Monthly Cost

```bash
# Kafka (3 brokers, m5.large)
Kafka: 3 × $1500/month = $4500/month

# Flink (4 tasks, on-demand)
Flink: 4 × $1000/month = $4000/month

# Firehose (assume 30 GB/day processed)
Firehose: 30 GB/day × 30 days × $0.24/GB = $200/month

# S3 (assume 900 GB stored)
S3: 900 GB × $0.023/GB = $20/month

# SageMaker Feature Store (assume 100M records)
SageMaker: 100M × $0.23/1M = $23/month

# Data Transfer (internal AWS, mostly free)
DT: ~$100/month (assume 1 TB cross-AZ)

# CloudWatch (metrics, logs)
CW: ~$30/month

# Total: ~$8700/month for 100K events/day
```

### 2. Cost Reduction Strategies

#### Use Spot Instances (Kafka Brokers)
```bash
# Edit project_config.json
{
  "kafka": {
    "use_spot": true,      // 70% cost reduction
    "spot_max_price": "0.50"
  }
}

# Tradeoff: Can be interrupted (multi-AZ handles it)
# Savings: $1500 → $450/month per broker
```

#### Reserve Instances (Flink)
```bash
# Reserve Flink tasks for 1 year (prepay)
# Savings: ~40% reduction (Reserved Instance Discount)

# Current: 4 tasks × $1000 = $4000/month
# Reserved: 4 tasks × $600 = $2400/month
# Savings: $1600/month (~$19K/year)
```

#### S3 Intelligent Tiering
```bash
# Automatically move old data to cheaper storage

aws s3api put-bucket-intelligent-tiering-configuration \
  --bucket $DATA_LAKE_BUCKET \
  --id AutoTiering \
  --intelligent-tiering-configuration '{
    "Id": "AutoTiering",
    "Filter": {"Prefix": ""},
    "Status": "Enabled",
    "Tierings": [
      {
        "Days": 30,
        "AccessTier": "ARCHIVE_ACCESS"
      },
      {
        "Days": 90,
        "AccessTier": "DEEP_ARCHIVE_ACCESS"
      }
    ]
  }'

# Savings: 70-95% after 30-90 days
```

#### Enable Firehose Compression
```bash
# Compress data before S3 (reduces transfer + storage)

aws firehose update-delivery-stream \
  --delivery-stream-name streaming-pipeline-firehose \
  --extended-s3-destination-update '{
    "CompressionFormat": "GZIP"  // or SNAPPY, ZIP
  }'

# Savings: 40-60% storage reduction (JSON → compressed)
```

#### Scale Down During Off-Hours
```bash
# Use Application Auto Scaling

aws application-autoscaling register-scalable-target \
  --service-namespace kinesis \
  --resource-id arn:aws:kinesis:REGION:ACCOUNT:app/NAME/123 \
  --scalable-dimension kinesis:table:WriteCapacityUnits \
  --min-capacity 2 \
  --max-capacity 32

# Create time-based scaling policy
aws application-autoscaling put-scheduled-action \
  --service-namespace kinesis \
  --resource-id arn:aws:kinesis:REGION:ACCOUNT:app/NAME/123 \
  --scalable-dimension kinesis:table:WriteCapacityUnits \
  --scheduled-action-name ScaleDownNight \
  --timezone "America/New_York" \
  --schedule "cron(0 18 * * ? *)" \  # 6 PM
  --scalable-target-action MinCapacity=1,MaxCapacity=4

# Scale up in morning
aws application-autoscaling put-scheduled-action \
  --service-namespace kinesis \
  --resource-id arn:aws:kinesis:REGION:ACCOUNT:app/NAME/123 \
  --scalable-dimension kinesis:table:WriteCapacityUnits \
  --scheduled-action-name ScaleUpMorning \
  --timezone "America/New_York" \
  --schedule "cron(0 6 * * ? *)" \  # 6 AM
  --scalable-target-action MinCapacity=4,MaxCapacity=32

# Savings: 30-40% during low-traffic hours
```

### 3. Monitor Costs

```bash
# Get daily cost breakdown
aws ce list-cost-allocation-tags --status Active

# View costs by service
aws ce get-cost-and-usage \
  --time-period Start=2026-01-01,End=2026-01-31 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=DIMENSION,Key=SERVICE

# Set up cost anomaly detection
aws ce create-anomaly-monitor \
  --anomaly-monitor '{
    "MonitorName": "StreamingPipelineCosts",
    "MonitorType": "DIMENSIONAL",
    "MonitorSpecification": {
      "Dimensions": {
        "Key": "SERVICE",
        "Values": ["Amazon Kinesis Analytics", "Amazon MSK"]
      }
    }
  }'
```

---

## Cleanup

### 1. Destroy Dev/Test Environment

```bash
# WARNING: This will delete all resources!

# List stacks to be deleted
cdk destroy --all --dry-run

# Destroy
cdk destroy --all --force

# Cleanup S3 buckets (CDK doesn't delete them by default)
aws s3 rm s3://$DATA_LAKE_BUCKET --recursive
aws s3 rb s3://$DATA_LAKE_BUCKET

# Remove KMS keys (if created manually)
aws kms schedule-key-deletion \
  --key-id arn:aws:kms:us-east-1:ACCOUNT:key/KEY_ID \
  --pending-window-in-days 7
```

### 2. Retain Important Data

```bash
# Before destroying, backup important data

# Export feature group
aws sagemaker-featurestore-runtime batch-get-record \
  --feature-group-name $FEATURE_GROUP_NAME \
  --record-identifiers-as-strings ["AMZN", "AAPL", "MSFT", "GOOGL"] \
  > features_backup.json

# Export Kafka topics (if needed)
kafka-mirror-maker.sh \
  --consumer.config source.properties \
  --producer.config dest.properties \
  --whitelist "input_topic|output_topic|dlq_topic"

# Backup S3 data
aws s3 cp s3://$DATA_LAKE_BUCKET ./local-backup --recursive
```

### 3. Cleanup AWS Resources

```bash
# Remove CloudTrail logging
aws cloudtrail delete-trail \
  --trail-name streaming-pipeline-trail

# Remove CloudWatch log groups
aws logs delete-log-group \
  --log-group-name /aws/kinesis-analytics/StreamingPipelineJob

aws logs delete-log-group \
  --log-group-name /aws/lambda/streaming-pipeline-producer

aws logs delete-log-group \
  --log-group-name /aws/vpc/streaming-pipeline

# Remove VPC Flow Logs
aws ec2 delete-flow-logs \
  --flow-log-ids fl-xxxxxxxx

# Remove SNS topics
aws sns delete-topic \
  --topic-arn arn:aws:sns:REGION:ACCOUNT:streaming-pipeline-alerts

# Remove CloudFormation stack
aws cloudformation delete-stack \
  --stack-name StreamingPipelineStack
```

---

## Summary

| Step | Duration | Purpose |
|------|----------|---------|
| Prerequisites | 15 min | Install tools, configure AWS |
| Setup | 10 min | Clone repo, create venv, update config |
| CDK Deploy | 20 min | Deploy infrastructure |
| Verification | 10 min | Test all components |
| Security Config | 10 min | Enable encryption, VPC logs |
| Monitoring | 5 min | Setup dashboards and alarms |
| **Total** | **70 min** | **Fully operational streaming pipeline** |

---

## Next Steps

1. **Monitor**: Check CloudWatch dashboards (Health, Performance, Errors, Capacity)
2. **Test**: Trigger test events through producer Lambda
3. **Trace**: Follow single event through system using correlation IDs in logs
4. **Scale**: Adjust Flink parallelism and Kafka brokers based on load
5. **Optimize**: Fine-tune checkpointing, windowing, and batching based on metrics

**For Incidents**: See [ALERT_RUNBOOKS.md](ALERT_RUNBOOKS.md) for step-by-step response procedures.

**For Architecture Details**: See [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions.

---

**Last Updated**: January 13, 2026  
**Status**: Production-Ready
