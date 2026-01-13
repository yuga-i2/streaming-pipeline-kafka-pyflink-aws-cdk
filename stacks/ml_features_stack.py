"""
Order ML Features Stack
=======================

This stack creates real-time ML features from order events using Amazon SageMaker
Feature Store. This enables low-latency feature lookups for real-time ML models.

Components:
- SageMaker Feature Group with online and offline storage
- Lambda function to consume orders from Kafka and write to Feature Store
- KMS encryption for feature data
- S3 bucket for offline feature store storage
- Event source mapping from Kafka to Lambda

Design Decisions:
1. Feature Store provides both online (low-latency) and offline (batch) storage
2. Online store (DynamoDB) enables sub-millisecond feature lookups for real-time inference
3. Offline store (S3) enables historical feature access for model training
4. Lambda with event source mapping provides automatic scaling based on Kafka throughput
5. Event ID = order_id ensures no duplicate feature entries
6. Event time = order_timestamp for temporal feature tracking

Use Cases:
- Fraud detection model: Look up customer history features in real-time
- Recommendation engine: Get recent customer order patterns instantly
- Churn prediction: Historical customer behavioral features for batch scoring
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    Tags,
    aws_ec2 as ec2,
)
from constructs import Construct
import json

from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.s3_helpers import S3Factory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.sm_feature_store_helpers import SageMakerFactory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.nag_helpers import NagSuppressionHelper


class MLFeaturesStack(Stack):
    """
    Creates SageMaker Feature Store for ML model feature serving.
    
    Outputs:
    - FeatureGroupName: Name of the created feature group
    - OnlineStoreName: Online store for real-time feature lookups
    - OfflineStoreBucket: S3 bucket for historical feature data
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: dict,
        event_streaming_stack: Stack,
        **kwargs
    ):
        super().__init__(scope, construct_id, **kwargs)

        self.config = config
        
        # Reference the event streaming stack resources
        vpc = event_streaming_stack.vpc
        kafka_cluster_arn = event_streaming_stack.kafka_cluster_arn
        orders_processed_topic = event_streaming_stack.orders_processed_topic
        kafka_lambda_layer = event_streaming_stack.kafka_lambda_layer
        
        # Extract configuration
        feature_store_config = config["ml_features"]
        feature_group_name = feature_store_config["feature_group_name"]
        
        # ======================================================================
        # STEP 1: Import Lambda security group from event streaming stack
        # ======================================================================
        lambda_security_group_id = cdk.Fn.import_value("EcommerceLambdaSecurityGroupId")
        lambda_security_group = ec2.SecurityGroup.from_security_group_id(
            self,
            "ImportedLambdaSG",
            security_group_id=lambda_security_group_id,
            allow_all_outbound=True,
        )

        # ======================================================================
        # STEP 2: Create S3 bucket for offline feature store
        # ======================================================================
        # Offline store is used for:
        # - Training ML models with historical features
        # - Batch feature retrieval (thousands of records at once)
        # - Data auditing and compliance
        sm_offline_feature_store_bucket = S3Factory.create_secure_bucket(
            scope=self,
            id="MLFeatureStoreBucket",
            bucket_name=f"ecommerce-ml-features-{self.account}",
        )

        # ======================================================================
        # STEP 3: Create KMS key for feature data encryption
        # ======================================================================
        # Encrypts:
        # - Online store (DynamoDB) data at rest
        # - Offline store (S3) data at rest
        # - Data in transit between services
        feature_store_key = SageMakerFactory.create_feature_store_kms_key(
            scope=self,
            id="MLFeatureStoreKey",
            description="KMS key for SageMaker Feature Store encryption (orders)"
        )

        # ======================================================================
        # STEP 4: Create IAM role for Feature Store operations
        # ======================================================================
        # Permissions:
        # - Read from S3 (offline store)
        # - Write to S3 (offline store)
        # - Encrypt/decrypt with KMS
        # - Write CloudWatch Logs for monitoring
        feature_store_role = SageMakerFactory.create_feature_store_role(
            scope=self,
            id="MLFeatureStoreRole",
            feature_store_bucket=sm_offline_feature_store_bucket,
            feature_store_key=feature_store_key,
            feature_group_name=feature_group_name,
            partition=self.partition,
            region=self.region,
            account=self.account,
        )

        # ======================================================================
        # STEP 5: Create SageMaker Feature Group
        # ======================================================================
        # Feature group defines:
        # - Feature record identifier (order_id - must be unique per order)
        # - Event time (order_timestamp - when the order occurred)
        # - Online storage enabled (DynamoDB for real-time lookups)
        # - Offline storage enabled (S3 for batch access)
        # - Feature time to live (TTL) - how long to keep features
        sm_feature_group = SageMakerFactory.create_feature_group(
            scope=self,
            id="OrderMLFeatureGroup",
            feature_group_name=feature_group_name,
            feature_store_bucket=sm_offline_feature_store_bucket,
            feature_store_key=feature_store_key,
            feature_store_role=feature_store_role,
            event_time_feature=feature_store_config["event_time_feature"],
            record_identifier_feature=feature_store_config["record_identifier_feature"],
        )

        # ======================================================================
        # STEP 6: Create Lambda function to ingest features into Feature Store
        # ======================================================================
        # This Lambda:
        # - Consumes from orders.processed Kafka topic
        # - Transforms order events into feature records
        # - Writes to both online (DynamoDB) and offline (S3) stores
        # - Handles errors and logs to CloudWatch
        # - Auto-scales with Kafka throughput via event source mapping
        feature_store_lambda = SageMakerFactory.create_feature_store_lambda(
            scope=self,
            id="OrderFeatureIngestor",
            vpc=vpc,
            security_group=lambda_security_group,
            layers=[kafka_lambda_layer],
            feature_group_name=feature_group_name,
            msk_cluster_arn=kafka_cluster_arn,
            kafka_topic=orders_processed_topic,
            consumer_group_id=feature_store_config["lambda"]["consumer_group_id"],
            batch_size=feature_store_config["lambda"]["function_event_source_batch_size"],
            timeout_seconds=feature_store_config["lambda"]["timeout_seconds"],
            memory_mb=feature_store_config["lambda"]["memory_mb"],
            feature_store_key=feature_store_key,
            partition=self.partition,
            region=self.region,
            account=self.account,
        )

        # ======================================================================
        # STEP 7: Output stack information
        # ======================================================================
        SageMakerFactory.output_feature_store_info(
            scope=self,
            feature_store_bucket=sm_offline_feature_store_bucket,
            feature_group=sm_feature_group,
            feature_store_lambda=feature_store_lambda,
        )

        CfnOutput(
            self,
            "FeatureGroupNameOutput",
            value=feature_group_name,
            description="SageMaker Feature Group name for order features",
            export_name="EcommerceOrderFeatureGroupName",
        )

        CfnOutput(
            self,
            "FeatureGroupOnlineStoreName",
            value=f"{feature_group_name}-online",
            description="Online store table name for real-time feature lookups",
            export_name="EcommerceOrderFeaturesOnlineStore",
        )

        CfnOutput(
            self,
            "OfflineStoreBucketOutput",
            value=sm_offline_feature_store_bucket.bucket_name,
            description="S3 bucket for offline feature store (historical data)",
            export_name="EcommerceOrderMLFeaturesOfflineStore",
        )

        # ======================================================================
        # STEP 8: Apply resource tags
        # ======================================================================
        Tags.of(self).add("Stack", "MLFeatures")
        Tags.of(self).add("Environment", config.get("environment", "dev"))

        # ======================================================================
        # STEP 9: CDK Nag Suppressions
        # ======================================================================
        # Suppress warnings about Lambda role permissions (necessary for Feature Store)
        NagSuppressionHelper.suppress_lambda_role_policies(
            scope=self,
            resources=[feature_store_lambda.role],
        )
