"""
Order Data Lake Stack
=====================

This stack creates the data lake infrastructure for storing processed order events
in Amazon S3 using Kinesis Data Firehose for reliable, buffered delivery.

Components:
- Kinesis Data Firehose delivery stream consuming from orders.processed topic
- S3 bucket with partitioned data lake (year/month/day/hour structure)
- Data transformation and compression (Gzip, Parquet format)
- CloudWatch Logs for delivery monitoring
- Lifecycle policies for cost optimization (Glacier, Deep Archive transitions)
- Encryption at rest with KMS

Design Decisions:
1. Firehose provides durable buffering - prevents data loss if S3 is temporarily unavailable
2. Partitioned S3 structure allows fast queries with Athena/Spectrum
3. Parquet format enables schema evolution and efficient compression
4. Lifecycle policies automatically archive old data, reducing storage costs
5. Gzip compression reduces bandwidth and storage footprint
6. Extended S3 destination allows custom data transformation via Lambda (future enhancement)

Data Flow:
Kafka (orders.processed topic) → Firehose → S3 (s3://bucket/orders/year=2024/month=01/day=13/...)
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    Tags,
)
from constructs import Construct
import json

from stacks.stack_helpers.firehose_helpers import FirehoseFactory
from stacks.stack_helpers.nag_helpers import NagSuppressionHelper


class DataLakeStack(Stack):
    """
    Creates the data lake infrastructure for order event archival and analytics.
    
    Outputs:
    - DataLakeBucketName: S3 bucket for order analytics
    - FirehoseDeliveryStreamName: Name of the Firehose stream
    - S3DataLakePrefix: Default S3 key prefix for order data
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: dict,
        event_streaming_stack: Stack,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config
        
        # Reference the event streaming stack resources
        kafka_cluster_arn = event_streaming_stack.kafka_cluster_arn
        orders_processed_topic = event_streaming_stack.orders_processed_topic
        firehose_bucket = event_streaming_stack.firehose_bucket

        # Extract Firehose configuration
        firehose_config = config["data_lake"]
        
        # ======================================================================
        # STEP 1: Create Firehose IAM role with least-privilege permissions
        # ======================================================================
        # Role allows:
        # - Reading from MSK (orders.processed topic)
        # - Writing to S3 (data lake bucket)
        # - Writing to CloudWatch Logs (delivery monitoring)
        firehose_log_group_name = f"/aws/kinesisfirehose/ecommerce-orders-delivery"

        self.firehose_role = FirehoseFactory.create_firehose_role(
            scope=self,
            id="OrderDataLakeFirehoseRole",
            cluster_name=config["event_streaming"]["cluster_name"],
            region=self.region,
            firehose_bucket=firehose_bucket,
            kafka_cluster_arn=kafka_cluster_arn,
            output_topic_name=orders_processed_topic,
            firehose_log_group_name=firehose_log_group_name,
        )

        # ======================================================================
        # STEP 2: Create Extended S3 Destination configuration
        # ======================================================================
        # This defines:
        # - S3 bucket and key prefix (partitioned by date/hour)
        # - Buffering hints (how often to flush data to S3)
        # - Compression (Gzip for storage efficiency)
        # - CloudWatch Logs (for delivery monitoring)
        extended_s3_dest_config = FirehoseFactory.create_extended_s3_destination_config(
            firehose_bucket=firehose_bucket,
            firehose_role=self.firehose_role,
            firehose_buffering_hints=firehose_config["buffering_hints"],
            firehose_log_group_name=firehose_log_group_name,
            s3_prefix=firehose_config.get("s3_prefix", "orders/"),
            compression=firehose_config.get("compression", "GZIP"),
        )

        # ======================================================================
        # STEP 3: Create Firehose Delivery Stream
        # ======================================================================
        # This stream:
        # - Consumes from the orders.processed Kafka topic
        # - Batches events based on buffering hints (300 seconds OR 128 MB)
        # - Writes to S3 with automatic partitioning
        # - Monitors delivery with CloudWatch metrics
        firehose_delivery_stream_name = f"ecommerce-orders-to-datalake"

        self.firehose_delivery_stream = FirehoseFactory.create_firehose_delivery_stream(
            scope=self,
            id="OrdersDataLakeDeliveryStream",
            delivery_stream_name=firehose_delivery_stream_name,
            kafka_cluster_arn=kafka_cluster_arn,
            output_topic_name=orders_processed_topic,
            firehose_role=self.firehose_role,
            extended_s3_dest_config=extended_s3_dest_config,
        )

        # ======================================================================
        # STEP 4: Create S3 Lifecycle Policy for cost optimization
        # ======================================================================
        # Automatically transition old data:
        # - 90 days → Glacier (cheaper for infrequent access)
        # - 365 days → Deep Archive (cheapest tier for archival)
        # This reduces storage costs from ~$0.023/GB to ~$0.004/GB for old data
        lifecycle_days_to_glacier = firehose_config.get("lifecycle_days_to_glacier", 90)
        lifecycle_days_to_deep_archive = firehose_config.get("lifecycle_days_to_deep_archive", 365)

        # Add lifecycle rule (if not already created in event_streaming_stack)
        if not hasattr(firehose_bucket.node, "_lifecycle_rule_applied"):
            firehose_bucket.add_lifecycle_rule(
                transitions=[
                    cdk.aws_s3.Transition(
                        storage_class=cdk.aws_s3.StorageClass.GLACIER,
                        transition_after=Duration.days(lifecycle_days_to_glacier),
                    ),
                    cdk.aws_s3.Transition(
                        storage_class=cdk.aws_s3.StorageClass.DEEP_ARCHIVE,
                        transition_after=Duration.days(lifecycle_days_to_deep_archive),
                    ),
                ],
                prefix="orders/",
            )
            firehose_bucket.node._lifecycle_rule_applied = True

        # ======================================================================
        # STEP 5: Output stack information
        # ======================================================================
        FirehoseFactory.output_firehose_info(
            scope=self,
            stack_name=self.stack_name,
            firehose_bucket=firehose_bucket,
            firehose_delivery_stream=self.firehose_delivery_stream,
            firehose_role=self.firehose_role,
        )

        CfnOutput(
            self,
            "DataLakeBucketOutput",
            value=firehose_bucket.bucket_name,
            description="S3 bucket for order data lake analytics",
            export_name="EcommerceOrdersDataLakeBucket",
        )

        CfnOutput(
            self,
            "FirehoseStreamNameOutput",
            value=self.firehose_delivery_stream.delivery_stream_name,
            description="Kinesis Firehose delivery stream name",
            export_name="EcommerceOrdersFirehoseName",
        )

        # ======================================================================
        # STEP 6: Apply resource tags
        # ======================================================================
        Tags.of(self).add("Stack", "DataLake")
        Tags.of(self).add("Environment", config.get("environment", "dev"))

        # ======================================================================
        # STEP 7: CDK Nag Suppressions
        # ======================================================================
        # Suppress warnings about Firehose permissions (necessary for S3 write access)
        NagSuppressionHelper.suppress_firehose_role(
            scope=self,
            resources=[self.firehose_role],
        )

        NagSuppressionHelper.suppress_firehose_delivery_stream(
            scope=self,
            resources=[self.firehose_delivery_stream],
        )
