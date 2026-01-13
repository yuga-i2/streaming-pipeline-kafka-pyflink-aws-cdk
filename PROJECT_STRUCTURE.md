# PROJECT_STRUCTURE.md

A complete folder-by-folder and file-by-file explanation of the repository structure.

---

## Directory Tree

```
streaming-pipeline-kafka-flink-firehose-s3-cdk/
│
├── app.py                                 [Root CDK App - Infrastructure Entry Point]
├── cdk.json                               [CDK Configuration]
├── project_config.json                    [Environment/Project Metadata]
├── requirements.txt                       [Python Dependencies (CDK)]
├── requirements-dev.txt                   [Development Dependencies (testing)]
│
├── config/                                [Environment-Specific Configurations]
│   ├── dev.json                          [Development Environment]
│   ├── staging.json                      [Staging Environment]
│   └── prod.json                         [Production Environment]
│
├── flink_pyflink_app/                    [PyFlink Stream Processing Application]
│   ├── __init__.py                       [Package Init]
│   ├── order_processor.py                [Main Flink Job]
│   ├── models.py                         [Data Models]
│   └── requirements.txt                  [PyFlink Dependencies]
│
├── stacks/  [CDK Infrastructure Stacks]
│   ├── event_streaming_stack.py          [Kafka MSK + Topics + Producer]
│   ├── order_processing_stack.py         [PyFlink Job Deployment]
│   ├── flink_stack.py                    [Flink Application Config]
│   ├── firehose_to_s3_stack.py           [Kinesis Firehose + S3]
│   ├── data_lake_stack.py                [S3 Data Lake Storage]
│   ├── ml_features_stack.py              [SageMaker Feature Store]
│   ├── msk_serverless_stack.py           [Kafka Cluster Topology]
│   └── stack_helpers/                    [Infrastructure Helper Modules]
│       ├── helper.py                     [Base/Common Helpers]
│       ├── ec2_helpers.py                [EC2 Bastion, Instances]
│       ├── iam_helpers.py                [IAM Roles & Policies]
│       ├── kms_helpers.py                [KMS Key Management & Encryption]
│       ├── lambda_helpers.py             [Lambda Function Creation]
│       ├── msk_helpers.py                [Kafka/MSK Configuration]
│       ├── flink_helpers.py              [Flink Job Deployment]
│       ├── firehose_helpers.py           [Kinesis Firehose Setup]
│       ├── s3_helpers.py                 [S3 Bucket Creation & Config]
│       ├── vpc_helpers.py                [VPC, Subnets, NAT Gateways]
│       ├── security_group_helpers.py     [Security Groups & Ingress/Egress]
│       ├── secure_iam_helpers.py         [Advanced IAM (service principals)]
│       ├── sm_feature_store_helpers.py   [SageMaker Feature Store Setup]
│       └── nag_helpers.py                [CDK NAG (security scanning)]
│
├── lambda/                                [AWS Lambda Functions]
│   ├── producer_lambda/                  [Event Producer]
│   │   └── producer.py                  [Lambda: Generates stock events]
│   ├── consumer_lambda/                  [Event Consumer]
│   │   └── consumer.py                  [Lambda: Consumes processed events]
│   ├── create_topic_lambda/              [Kafka Topic Creation]
│   │   ├── create_topic.py              [Lambda: Creates input/output topics]
│   │   └── requirements.txt              [Dependencies]
│   ├── feature_store_lambda/             [SageMaker Integration]
│   │   └── feature_store_lambda.py      [Lambda: Ingests into Feature Store]
│   └── check_feature_store_lambda/       [Feature Store Validation]
│       └── check_feature_store_records.py [Lambda: Validates stored features]
│
├── tests/                                 [Unit Tests]
│   └── unit/
│       └── test_streaming_pipeline_kafka_flink_firehose_s3_cdk_stack.py
│
├── diagrams/                              [Architecture Diagrams]
│   ├── Architecture_diagram.png          [Visual overview]
│   └── Architecture_diagram.drawio       [Source (editable)]
│
├── .gitignore                             [Git Ignore Rules]
├── LICENSE                                [MIT License]
├── CODE_OF_CONDUCT.md                     [Community Guidelines]
├── CONTRIBUTING.md                        [How to Contribute]
├── README.md                              [Project Overview - START HERE]
├── PROJECT_STRUCTURE.md                   [This File - Navigation Guide]
├── ARCHITECTURE.md                        [Technical Deep Dive]
├── DEPLOYMENT.md                          [Setup & Operations]
├── IMPLEMENTATION_GUIDE.md                [Design Rationale & Interview]
├── OBSERVABILITY.md                       [Monitoring & Metrics]
├── FAILURE_MODES_AND_DETECTION.md        [Reliability Strategy]
└── ALERT_RUNBOOKS.md                      [Incident Response]
```

---

## Core Files & Directories

### `app.py` (200 lines)
**Purpose**: Main AWS CDK application entry point  
**What it does**:
- Imports all stack definitions
- Reads `project_config.json` for environment settings
- Instantiates each stack (MSK, Flink, Firehose, FeatureStore)
- Passes configuration to stacks
- Outputs important values (Kafka endpoints, S3 buckets, etc.)

**How to use**: Run `cdk deploy --all` to deploy all stacks via this file

---

### `config/` Directory
**Purpose**: Environment-specific configuration files

**Files**:
- `dev.json` - Development environment (small resources, test data)
- `staging.json` - Staging environment (prod-like, validation)
- `prod.json` - Production environment (optimized resources, scaling)

**What's in each**:
```json
{
  "region": "us-east-1",
  "environment": "dev",
  "flink": {
    "artifact_bucket_name": "your-bucket",
    "parallelism": 2,
    "checkpoint_interval_ms": 10000
  },
  "kafka": {
    "broker_count": 2,
    "instance_type": "kafka.m5.large"
  }
}
```

---

## PyFlink Application

### `flink_pyflink_app/` Directory
**Purpose**: The actual stream processing job that runs on Flink

**Files**:

#### `order_processor.py` (400 lines)
**What it does**:
- Reads from Kafka `input_topic`
- Validates and enriches events
- Applies windowing (1-minute tumbling windows)
- Computes aggregations (sum, count, avg)
- Sends errors to DLQ topic
- Writes results to `output_topic`
- Emits CloudWatch metrics and structured logs

**Key components**:
- `StreamExecutionEnvironment` - Entry point
- Kafka source/sink - Connect to Kafka cluster
- Data validation - Check required fields
- Window operator - 1-minute aggregation
- Metrics reporter - Send to CloudWatch
- Error handler - Catch and log invalid data

**Usage**: Deployed to Amazon Managed Flink via CDK

#### `models.py` (150 lines)
**What it does**:
- Defines data models (Pydantic classes)
- Models: `StockPrice`, `StockAggregate`, `FeatureStoreRecord`
- Validation logic for each model
- Serialization/deserialization helpers

**Example**:
```python
class StockPrice:
    ticker: str
    price: float
    volume: int
    timestamp: int  # Unix timestamp
```

#### `requirements.txt`
**What's in it**: PyFlink dependencies
```
pyflink==1.15.0
pydantic==1.10.0
```

---

## AWS CDK Infrastructure

### `streaming_pipeline_kafka_flink_firehose_s3_cdk/` Directory
**Purpose**: All infrastructure-as-code definitions

**Main Stacks** (7 stack files):

#### `event_streaming_stack.py` (300 lines)
**Provisions**:
- MSK Serverless Kafka cluster
- VPC and networking (private subnets)
- Kafka topics: `input_topic`, `output_topic`, `dlq_topic`
- Producer Lambda function (triggered by EventBridge every minute)
- Topic creation Lambda (custom resource)
- EC2 bastion host (for Kafka administration)
- Security groups for Kafka access

**Outputs**: Kafka bootstrap servers, topic names

---

#### `flink_stack.py` (200 lines)
**Provisions**:
- PyFlink application definition
- Flink runtime configuration (parallelism, checkpoints)
- CloudWatch log group for Flink
- RocksDB state backend configuration
- Logging and metrics setup

---

#### `order_processing_stack.py` (250 lines)
**Provisions**:
- IAM role for Flink job (read Kafka, write metrics, access state)
- Flink job deployment properties
- Kafka consumer group configuration
- State backend (RocksDB in S3)
- CloudWatch monitoring setup

---

#### `firehose_to_s3_stack.py` (300 lines)
**Provisions**:
- Kinesis Data Firehose delivery stream
- Consumes from Kafka `output_topic`
- Buffers data (size and time based)
- Delivers to S3 in Parquet format
- Partitioned by date (s3://bucket/year=2026/month=01/day=13/)
- CloudWatch monitoring

---

#### `data_lake_stack.py` (200 lines)
**Provisions**:
- S3 bucket for data lake storage
- Versioning, encryption, access logging
- Lifecycle policies (archive old data)
- Bucket policies (restrict access)
- Glue catalog integration (for Athena queries)

---

#### `ml_features_stack.py` (250 lines)
**Provisions**:
- SageMaker Feature Group
- Online and offline storage
- IAM role for feature store
- Feature Group schema definition
- Lambda function for feature ingestion

---

#### `msk_serverless_stack.py` (200 lines)
**Provisions**:
- MSK Serverless cluster configuration
- VPC configuration (subnets, security groups)
- Broker configuration
- Multi-AZ setup

---

### `stack_helpers/` Directory
**Purpose**: Reusable infrastructure building blocks

**What's here**: 13 helper modules, each handling one aspect of infrastructure

| Helper | Provides |
|--------|----------|
| `helper.py` | Common utilities, tag generation |
| `ec2_helpers.py` | Bastion host, instances |
| `iam_helpers.py` | IAM roles, policies (least-privilege) |
| `kms_helpers.py` | KMS keys, encryption |
| `lambda_helpers.py` | Lambda function creation, permissions |
| `msk_helpers.py` | Kafka cluster configuration |
| `flink_helpers.py` | Flink job setup, deployment |
| `firehose_helpers.py` | Kinesis Firehose, delivery configuration |
| `s3_helpers.py` | S3 buckets, policies, encryption |
| `vpc_helpers.py` | VPC, subnets, NAT gateways, routing |
| `security_group_helpers.py` | Security groups, inbound/outbound rules |
| `secure_iam_helpers.py` | Advanced IAM (service principals, conditions) |
| `sm_feature_store_helpers.py` | SageMaker setup |
| `nag_helpers.py` | CDK NAG (security best practices scanning) |

**Example: `iam_helpers.py`**
```python
def create_flink_role(scope, stack_name, kafka_arn, s3_arn):
    # Creates least-privilege IAM role for Flink
    # Grants: Read from Kafka, Write to S3, CloudWatch metrics
    # Denies: Everything else
```

**Key principle**: Each helper is **reusable** and **independent** (low coupling)

---

## Lambda Functions

### `lambda/` Directory
**Purpose**: Event-driven serverless functions

#### `producer_lambda/producer.py` (100 lines)
**Triggered by**: EventBridge (every 1 minute)  
**Does**:
- Generates random stock data (AMZN, AAPL, MSFT, GOOGL)
- Publishes to Kafka `input_topic`
- Logs with correlation ID

#### `consumer_lambda/consumer.py` (80 lines)
**Triggered by**: Manual invocation or EventBridge  
**Does**:
- Reads from Kafka `output_topic`
- Logs the processed results
- Useful for monitoring/debugging

#### `create_topic_lambda/create_topic.py` (120 lines)
**Triggered by**: CDK custom resource (during deployment)  
**Does**:
- Creates Kafka topics if they don't exist
- Sets retention policies
- Ensures idempotency (safe to run multiple times)

#### `feature_store_lambda/feature_store_lambda.py` (150 lines)
**Triggered by**: Kafka trigger (reads from `output_topic`)  
**Does**:
- Consumes processed aggregations
- Writes to SageMaker Feature Group (online store)
- Logs feature store API calls

#### `check_feature_store_lambda/check_feature_store_records.py` (100 lines)
**Triggered by**: Scheduled (every 5 minutes)  
**Does**:
- Queries Feature Group for recent records
- Validates data quality
- Emits metrics (record count, age, etc.)

---

## Tests

### `tests/unit/` Directory
**Purpose**: Unit tests for CDK stacks

**File**: `test_streaming_pipeline_kafka_flink_firehose_s3_cdk_stack.py` (200 lines)

**Tests**:
- Stack instantiation (no errors)
- Template generation (valid CloudFormation)
- Resource existence (check if resources created)
- IAM policies (verify least-privilege)
- Security groups (verify access rules)

**Run tests**: `pytest tests/unit/`

---

## Documentation

### Primary Docs (Start Here)
1. **README.md** - Overview, quick start, what to read next
2. **PROJECT_STRUCTURE.md** - This file, navigation guide

### Technical Docs
3. **ARCHITECTURE.md** - Data flow, design decisions, Flink concepts
4. **DEPLOYMENT.md** - Step-by-step setup, security, troubleshooting
5. **IMPLEMENTATION_GUIDE.md** - Interview-ready answers, "why these choices"

### Operations Docs
6. **OBSERVABILITY.md** - 40+ metrics, 11 alarms, 4 dashboards
7. **FAILURE_MODES_AND_DETECTION.md** - What can go wrong, how to detect
8. **ALERT_RUNBOOKS.md** - Step-by-step incident response

---

## Configuration Files

### `cdk.json`
**What it is**: CDK configuration  
**Contains**:
```json
{
  "app": "python3 app.py",
  "context": {
    "max_worker_threads": 10,
    "suppress_output_warnings": false
  }
}
```

### `project_config.json`
**What it is**: Application-level configuration  
**Contains**:
```json
{
  "flink": {
    "artifact_bucket_name": "your-bucket-name",
    "parallelism": 4,
    "checkpoint_interval_ms": 10000
  },
  "kafka": {
    "broker_count": 3,
    "instance_type": "kafka.m5.large"
  },
  "firehose": {
    "buffer_size_mb": 128,
    "buffer_time_seconds": 60
  }
}
```

### `requirements.txt`
**What it is**: Python dependencies for CDK  
**Contains**:
```
aws-cdk-lib==2.60.0
constructs==10.0.0
pydantic==1.10.0
boto3==1.26.0
```

### `requirements-dev.txt`
**What it is**: Development dependencies (testing, linting)  
**Contains**:
```
pytest==7.4.0
black==23.7.0
pylint==2.17.0
```

---

## Key Files by Use Case

### "I want to understand the architecture"
→ Read: `ARCHITECTURE.md`

### "I want to deploy this"
→ Read: `DEPLOYMENT.md` + `config/{dev|staging|prod}.json`

### "I want to understand the code"
→ Start: `flink_pyflink_app/order_processor.py` + `streaming_pipeline_*/event_streaming_stack.py`

### "How do I monitor this?"
→ Read: `OBSERVABILITY.md`

### "An alarm fired, what do I do?"
→ Read: `ALERT_RUNBOOKS.md`

### "I'm in an interview, what should I know?"
→ Read: `IMPLEMENTATION_GUIDE.md` + `ARCHITECTURE.md`

### "I need to scale/modify something"
→ Edit: `config/{environment}.json` → Run: `cdk deploy`

### "I need to add a new Lambda"
→ Create: `lambda/new_function/` → Update: `app.py` → Run: `cdk deploy`

---

## Dependency Graph

```
app.py
├── event_streaming_stack.py
│   ├── msk_serverless_stack.py
│   ├── producer_lambda/
│   ├── create_topic_lambda/
│   └── stack_helpers/ (many)
│
├── order_processing_stack.py
│   ├── flink_stack.py
│   ├── data_lake_stack.py
│   └── stack_helpers/
│
├── firehose_to_s3_stack.py
│   ├── data_lake_stack.py
│   └── stack_helpers/
│
├── ml_features_stack.py
│   ├── feature_store_lambda/
│   └── stack_helpers/
│
└── CloudWatch alarms (cloudwatch_alarms.py)
    └── OBSERVABILITY.md
```

**Data Flow**:
```
EventBridge triggers → producer_lambda → Kafka input_topic
                                         ↓
                                  PyFlink job (order_processor.py)
                                  ├─ errors → dlq_topic
                                  └─ results → output_topic
                                       ↓
                                  ├─ Firehose → S3 (data_lake_stack)
                                  └─ feature_store_lambda → SageMaker
```

---

## Summary

| Folder | Purpose | Audience |
|--------|---------|----------|
| `/` | Config and entry | DevOps |
| `config/` | Environments | DevOps |
| `flink_pyflink_app/` | Stream job | Engineers |
| `streaming_pipeline_*` | Infrastructure | Architects |
| `lambda/` | Serverless functions | Engineers |
| `tests/` | Unit tests | QA/DevOps |
| `diagrams/` | Visual docs | Everyone |

**Total**: 60+ files organized in 8 main directories

**Time to understand**: 15-20 minutes reading this file + source code

---

## Navigation Quick Links

- [Back to README](README.md)
- [ARCHITECTURE.md](ARCHITECTURE.md) - How it works
- [DEPLOYMENT.md](DEPLOYMENT.md) - How to deploy
- [OBSERVABILITY.md](OBSERVABILITY.md) - How to monitor
