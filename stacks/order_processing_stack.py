"""
Order Processing Stack (PyFlink)
================================

This stack deploys Amazon Managed Service for Apache Flink for real-time stream
processing of order events. Uses PyFlink (Python API for Apache Flink) for faster
development iteration and integration with Python ecosystem.

Components:
- Apache Flink managed application (Python-based via PyFlink 1.20)
- Auto-scaling configuration based on CPU/memory utilization
- CloudWatch Logs for application monitoring
- IAM role with least-privilege permissions

Processing Logic (flink_pyflink_app/order_processor.py):
1. Validate: Schema validation + business rule enforcement → DLQ on failure
2. Enrich: Add region, tax, category based on customer_id
3. Deduplicate: Keyed state (order_id) prevents duplicate processing
4. Aggregate: 5-minute tumbling windows by region → order count/totals
5. Output: 
   - ecommerce.orders.processed (enriched orders)
   - ecommerce.orders.dlq (validation failures)
   - ecommerce.orders.aggregations (windowed metrics)

Design Decisions:
1. PyFlink chosen for development velocity + AWS Managed Flink native support
2. Event-time semantics with 10-minute allowed lateness (watermarking)
3. Exactly-once semantics via 60-second checkpointing + RocksDB state backend
4. Keyed state for regional aggregations (parallelism matches Kafka partitions)
5. DLQ pattern enables operational visibility into data quality issues
6. Deduplication prevents double-charging (financial safeguard)

Dependencies:
- flink_pyflink_app directory contains PyFlink application code
- S3 bucket for Python artifacts and state backend persistence
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    CfnOutput,
    Tags,
)
from constructs import Construct
import json

from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.helper import (
    get_topic_name,
    get_group_name,
)
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.security_group_helpers import (
    SecurityGroupFactory,
)
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.flink_helpers import FlinkFactory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.nag_helpers import NagSuppressionHelper


class OrderProcessingStack(Stack):
    """
    Creates the Flink stream processing application for order events.
    
    Outputs:
    - FlinkApplicationName: Name of the deployed Flink application
    - FlinkApplicationArn: ARN for monitoring and control
    - FlinkLogGroup: CloudWatch log group for application logs
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: dict,
        event_streaming_stack: Stack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        # Reference the event streaming stack resources
        vpc = event_streaming_stack.vpc
        kafka_cluster_arn = event_streaming_stack.kafka_cluster_arn
        orders_raw_topic = event_streaming_stack.orders_raw_topic
        orders_processed_topic = event_streaming_stack.orders_processed_topic
        artifact_bucket = event_streaming_stack.artifact_bucket

        # Extract Flink configuration
        flink_config = config["stream_processor"]
        
        # ======================================================================
        # STEP 1: Import Kafka security group from event streaming stack
        # ======================================================================
        kafka_security_group_id = cdk.Fn.import_value("EcommerceKafkaSecurityGroupId")
        kafka_security_group = ec2.SecurityGroup.from_security_group_id(
            self,
            "ImportedKafkaSG",
            security_group_id=kafka_security_group_id,
            allow_all_outbound=True,
        )

        # ======================================================================
        # STEP 2: Create Flink-specific security group
        # ======================================================================
        # Controls what Flink can communicate with:
        # - MSK cluster (port 9098 for IAM auth)
        # - S3 (via gateway endpoint)
        # - CloudWatch (via HTTPS)
        self.flink_security_group = SecurityGroupFactory.create_flink_security_group(
            scope=self,
            id="OrderProcessorSecurityGroup",
            vpc=vpc,
        )

        # Allow Flink to communicate with MSK
        kafka_security_group.connections.allow_from(
            self.flink_security_group,
            ec2.Port.tcp(9098),
            "Allow Flink to MSK broker",
        )

        # ======================================================================
        # STEP 3: Create CloudWatch Log Group for Flink application
        # ======================================================================
        # Collects:
        # - Application startup/shutdown logs
        # - Processing errors and exceptions
        # - Custom application logs via SLF4J
        # - Flink runtime metrics (via custom metrics)
        self.flink_log_group = FlinkFactory.create_flink_log_group(
            scope=self,
            id="OrderProcessorLogGroup",
            log_group_name=f"/aws/kinesisanalytics/{flink_config['application_name']}",
        )

        # ======================================================================
        # STEP 4: Create IAM role for Flink application
        # ======================================================================
        # Permissions:
        # - Read from MSK (orders.raw topic)
        # - Write to MSK (orders.processed, orders.dlq topics)
        # - Write to S3 (state backend, savepoints)
        # - Write CloudWatch Logs (application logs)
        # - (Optional) Decrypt KMS for encrypted Kafka
        self.flink_role = FlinkFactory.create_flink_role(
            scope=self,
            id="OrderProcessorRole",
            account_id=self.account,
            region=self.region,
            application_name=flink_config["application_name"],
            msk_cluster_arn=kafka_cluster_arn,
        )

        # Grant CloudWatch write permissions
        self.flink_log_group.grant_write(self.flink_role)

        # ======================================================================
        # STEP 5: Create Flink Application
        # ======================================================================
        # Configuration:
        # - Input: orders.raw topic (raw order events)
        # - Output: orders.processed topic (enriched orders)
        # - DLQ: orders.dlq topic (validation failures)
        # - Metrics: orders.aggregations topic (windowed metrics)
        # - Parallelism: configurable per environment (2=dev, 4=staging, 16=prod)
        # - Checkpoint interval: 60 seconds for exactly-once semantics
        # - Bootstrap servers: MSK cluster endpoints
        # - Entrypoint: Python script in S3 (PyFlink 1.20)
        self.flink_app = FlinkFactory.create_pyflink_application(
            scope=self,
            id="OrderProcessorApplication",
            application_name=flink_config["application_name"],
            artifact_bucket=artifact_bucket,
            python_script_path=flink_config["python_script_path"],  # e.g., "flink_pyflink_app/order_processor.py"
            log_group=self.flink_log_group,
            role=self.flink_role,
            vpc=vpc,
            security_groups=[self.flink_security_group],
            bootstrap_brokers="",  # Set via environment variable
            input_topic=orders_raw_topic,
            output_topic=orders_processed_topic,
            parallelism=flink_config.get("parallelism", 4),
        )

        # Grant S3 permissions for state backend
        artifact_bucket.grant_read_write(self.flink_role)

        # ======================================================================
        # STEP 6: Output application information
        # ======================================================================
        CfnOutput(
            self,
            "FlinkApplicationNameOutput",
            value=flink_config["application_name"],
            description="Name of the Flink application",
            export_name="EcommerceOrderProcessorApplicationName",
        )

        CfnOutput(
            self,
            "FlinkApplicationArnOutput",
            value=f"arn:aws:kinesisanalytics:{self.region}:{self.account}:application/{flink_config['application_name']}",
            description="ARN of the Flink application for monitoring",
            export_name="EcommerceOrderProcessorApplicationArn",
        )

        CfnOutput(
            self,
            "FlinkLogGroupOutput",
            value=self.flink_log_group.log_group_name,
            description="CloudWatch log group for Flink application logs",
            export_name="EcommerceOrderProcessorLogGroup",
        )

        # ======================================================================
        # STEP 7: Apply resource tags
        # ======================================================================
        Tags.of(self).add("Stack", "OrderProcessing")
        Tags.of(self).add("Environment", config.get("environment", "dev"))

        # ======================================================================
        # STEP 8: CDK Nag Suppressions
        # ======================================================================
        # Suppress warnings about Flink role permissions (necessary for stream processing)
        NagSuppressionHelper.suppress_flink_application_role(
            scope=self,
            resources=[self.flink_role],
        )
