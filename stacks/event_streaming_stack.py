"""
E-Commerce Event Streaming Stack
=================================

This stack creates the core messaging infrastructure for the e-commerce order 
processing pipeline using Amazon MSK Serverless (managed Kafka).

Components:
- VPC with public/private subnets and VPC Flow Logs for network monitoring
- MSK Serverless cluster with automatic scaling and IAM authentication
- Kafka topics: orders.raw (inbound), orders.processed (outbound), orders.dlq (failed events)
- EventBridge rule triggered Lambda for generating order events
- Lambda Layer for Kafka libraries (boto3, kafka-python)
- Bastion host for Kafka administration (optional, controlled by config)
- Security groups with least-privilege network policies

Design Decisions:
1. MSK Serverless eliminates operational overhead vs. self-managed Kafka
2. IAM authentication replaces SASL/SSL for tighter AWS integration
3. Topic partitioning allows parallel processing across order regions
4. Separate DLQ topic captures failed events for operational debugging
"""

from aws_cdk import (
    RemovalPolicy,
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_ec2 as ec2,
    aws_lambda_python_alpha as _alambda,
    aws_events as events,
    aws_events_targets as targets,
    CfnOutput,
    CustomResource,
    custom_resources as cr,
    Tags,
)
from constructs import Construct
import json

# Import helper modules
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.helper import get_topic_name, get_group_name
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.vpc_helpers import VPCFactory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.security_group_helpers import SecurityGroupFactory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.s3_helpers import S3Factory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.ec2_helpers import EC2Factory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.msk_helpers import MSKFactory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.lambda_helpers import LambdaFactory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.iam_helpers import MSKPolicyFactory
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.nag_helpers import NagSuppressionHelper


class EventStreamingStack(Stack):
    """
    Creates the event streaming infrastructure for e-commerce order processing.
    
    Outputs:
    - KafkaClusterArn: ARN of the MSK cluster for cross-stack references
    - KafkaBootstrapServers: Connection string for Flink and other consumers
    - OrdersRawTopicName: Name of the input topic for raw orders
    - OrdersProcessedTopicName: Name of the output topic for processed orders
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: dict,
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Extract configuration
        self.config = config
        cluster_id = config["event_streaming"]["cluster_id"]
        cluster_name = config["event_streaming"]["cluster_name"]
        
        # Topic names from config
        self.orders_raw_topic = config["event_streaming"]["topics"]["orders_raw"]["name"]
        self.orders_processed_topic = config["event_streaming"]["topics"]["orders_processed"]["name"]
        self.orders_dlq_topic = config["event_streaming"]["topics"]["orders_dlq"]["name"]

        # ======================================================================
        # STEP 1: Create VPC with flow logs for network monitoring
        # ======================================================================
        vpc = VPCFactory.create_vpc_with_flow_logs(
            scope=self,
            id="EventStreamingVPC",
            cidr_range=config["vpc"]["cidr_range"],
            cidr_mask=config["vpc"]["cidr_mask"],
        )
        self.vpc = vpc

        # ======================================================================
        # STEP 2: Create Kafka security group (controls network access to MSK)
        # ======================================================================
        kafka_security_group = SecurityGroupFactory.create_kafka_security_group(
            scope=self,
            id="KafkaSecurityGroup",
            vpc=vpc,
        )
        self.kafka_security_group = kafka_security_group

        # Export the security group for other stacks to import
        CfnOutput(
            self,
            "KafkaSecurityGroupIdOutput",
            value=kafka_security_group.security_group_id,
            description="Security group ID for Kafka clients (Flink, Lambda)",
            export_name="EcommerceKafkaSecurityGroupId",
        )

        # ======================================================================
        # STEP 3: Create MSK Serverless cluster
        # ======================================================================
        # MSK Serverless automatically scales based on traffic
        # Uses IAM authentication (no username/password or SASL)
        kafka_cluster = MSKFactory.create_serverless_cluster(
            scope=self,
            id=cluster_id,
            cluster_name=cluster_name,
            vpc=vpc,
            security_group=kafka_security_group,
        )
        self.kafka_cluster_arn = kafka_cluster.attr_arn

        # ======================================================================
        # STEP 4: Create MSK Cluster Policy
        # ======================================================================
        # This policy allows the cluster to be accessed by clients with IAM creds
        MSKFactory.create_cluster_policy(
            scope=self,
            id="EventStreamingClusterPolicy",
            cluster_arn=self.kafka_cluster_arn,
        )

        # ======================================================================
        # STEP 5: Output cluster information for cross-stack references
        # ======================================================================
        MSKFactory.output_cluster_info(
            scope=self,
            cluster_arn=self.kafka_cluster_arn,
            cluster_name=cluster_name,
        )

        # ======================================================================
        # STEP 6: Create bastion host (optional - for Kafka administration)
        # ======================================================================
        if config["bastion_host"].get("enabled", True):
            bastion_security_group = SecurityGroupFactory.create_bastion_host_security_group(
                scope=self,
                id="BastionHostSecurityGroup",
                vpc=vpc,
                description=config["bastion_host"].get("description", "Bastion host for Kafka admin"),
            )

            bastion_instance = EC2Factory.create_bastion_host(
                scope=self,
                id="KafkaAdminBastionHost",
                vpc=vpc,
                security_group=bastion_security_group,
                instance_type=config["bastion_host"]["instance_type"],
            )

            EC2Factory.add_kafka_client_user_data(
                instance=bastion_instance,
                kafka_cluster_arn=self.kafka_cluster_arn,
                region=self.region,
            )

            CfnOutput(
                self,
                "BastionHostIdOutput",
                value=bastion_instance.instance_id,
                description="Bastion host instance ID for Kafka administration",
                export_name="EcommerceBastionHostId",
            )

            # Add least-privilege Kafka permissions to bastion
            # (removed AmazonS3FullAccess for security improvement)
            bastion_instance.add_to_role_policy(
                MSKPolicyFactory.get_cluster_access_policy(self.kafka_cluster_arn)
            )
            bastion_instance.add_to_role_policy(
                MSKPolicyFactory.get_topic_admin_policy(self.kafka_cluster_arn)
            )
            bastion_instance.add_to_role_policy(
                MSKPolicyFactory.get_group_access_policy(self.kafka_cluster_arn)
            )

            self.bastion_instance = bastion_instance

        # ======================================================================
        # STEP 7: Create Lambda Layer with Kafka libraries
        # ======================================================================
        kafka_lambda_layer = _alambda.PythonLayerVersion(
            self,
            "KafkaClientLayer",
            entry="./lambda_layer/kafka_layer/",
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            compatible_architectures=[_lambda.Architecture.ARM_64],
        )
        self.kafka_lambda_layer = kafka_lambda_layer

        # ======================================================================
        # STEP 8: Create Lambda security group for event producer
        # ======================================================================
        lambda_security_group = SecurityGroupFactory.create_lambda_security_group(
            scope=self,
            id="EventProducerSecurityGroup",
            vpc=vpc,
            description="Security group for order event producer Lambda",
        )

        CfnOutput(
            self,
            "LambdaSecurityGroupIdOutput",
            value=lambda_security_group.security_group_id,
            description="Security group ID for Lambda functions that access Kafka",
            export_name="EcommerceLambdaSecurityGroupId",
        )

        # ======================================================================
        # STEP 9: Create topic creation Lambda (Custom Resource)
        # ======================================================================
        # This Lambda runs once during stack deployment to create Kafka topics
        create_topic_lambda = LambdaFactory.create_topic_admin_lambda(
            scope=self,
            id="TopicCreationLambda",
            code_path="./lambda/create_topic_lambda/",
            vpc=vpc,
            security_group=lambda_security_group,
            layers=[kafka_lambda_layer],
            kafka_cluster_arn=self.kafka_cluster_arn,
            input_topic_name=self.orders_raw_topic,
            output_topic_name=self.orders_processed_topic,
            environment={
                "DLQ_TOPIC_NAME": self.orders_dlq_topic,
            }
        )

        # Create custom resource that triggers the Lambda
        topic_creation_custom_resource = CustomResource(
            self,
            "TopicCreationCustomResource",
            service_token=create_topic_lambda.function_arn,
            properties={
                "Topics": [
                    self.orders_raw_topic,
                    self.orders_processed_topic,
                    self.orders_dlq_topic,
                ]
            },
        )

        # ======================================================================
        # STEP 10: Create EventBridge rule to trigger order producer Lambda
        # ======================================================================
        # Generates synthetic orders every minute (configurable)
        producer_schedule_rule = events.Rule(
            self,
            "OrderProducerScheduleRule",
            schedule=events.Schedule.rate(Duration.minutes(1)),
            description="Triggers order producer Lambda to generate test orders every minute",
        )

        # ======================================================================
        # STEP 11: Create order producer Lambda
        # ======================================================================
        producer_lambda = LambdaFactory.create_kafka_lambda(
            scope=self,
            id="OrderProducerLambda",
            handler="producer.lambda_handler",
            code_path="./lambda/producer_lambda/",
            vpc=vpc,
            security_group=lambda_security_group,
            layers=[kafka_lambda_layer],
            kafka_cluster_arn=self.kafka_cluster_arn,
            environment={
                "MSK_BOOTSTRAP_SERVERS": "",  # Will be set via custom resource
                "TOPIC_NAME": self.orders_raw_topic,
                "LOG_LEVEL": config["observability"].get("log_level", "INFO"),
            },
            memory_size=256,
            timeout=Duration.seconds(60),
            description="Generates synthetic e-commerce order events",
        )

        # Trigger Lambda on schedule
        producer_schedule_rule.add_target(targets.LambdaFunction(producer_lambda))

        CfnOutput(
            self,
            "ProducerLambdaArn",
            value=producer_lambda.function_arn,
            description="ARN of the order producer Lambda",
            export_name="EcommerceOrderProducerLambdaArn",
        )

        # ======================================================================
        # STEP 12: Create S3 buckets for artifacts
        # ======================================================================
        # Artifact bucket for Flink JAR files
        artifact_bucket = S3Factory.create_artifact_bucket(
            scope=self,
            id="FlinkArtifactBucket",
            bucket_name=config["stream_processor"]["artifact_bucket_name"].replace("${ACCOUNT_ID}", self.account),
        )
        self.artifact_bucket = artifact_bucket

        # Output bucket for processed orders
        output_bucket = S3Factory.create_output_bucket(
            scope=self,
            id="OrdersOutputBucket",
            bucket_name=f"ecommerce-orders-output-{self.account}",
        )
        self.output_bucket = output_bucket

        # Data lake bucket for historical data
        firehose_bucket = S3Factory.create_output_bucket(
            scope=self,
            id="OrdersDataLakeBucket",
            bucket_name=f"{config['data_lake']['bucket_prefix']}-{self.account}",
        )
        self.firehose_bucket = firehose_bucket

        # ======================================================================
        # STEP 13: Apply resource tags for cost tracking and organization
        # ======================================================================
        Tags.of(self).add("Stack", "EventStreaming")
        Tags.of(self).add("Environment", config.get("environment", "dev"))
        
        # ======================================================================
        # STEP 14: CDK Nag Suppressions (security check exceptions)
        # ======================================================================
        # Suppress security warnings for bastion host (necessary for admin access)
        if config["bastion_host"].get("enabled", True):
            NagSuppressionHelper.suppress_lambda_role_policies(
                scope=self,
                resources=[bastion_instance.role, create_topic_lambda.role],
            )

        NagSuppressionHelper.suppress_lambda_runtime(
            scope=self,
            resources=[create_topic_lambda],
        )
