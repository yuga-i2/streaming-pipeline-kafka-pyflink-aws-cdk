## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import (
    RemovalPolicy,
    aws_iam as iam,
    aws_logs as logs,
    aws_kinesisanalytics_flink_alpha as flink,
    aws_ec2 as ec2,
    aws_s3_assets as s3_assets,
    CfnOutput,
)
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.helper import get_topic_name, get_group_name
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.iam_helpers import MSKPolicyFactory

class FlinkFactory:
    """
    Factory class for creating and configuring Flink applications and related resources.
    
    Supports:
    - PyFlink applications (Python-based, recommended for faster development)
    - Java Flink applications (legacy, for performance-critical workloads)
    """
    
    @staticmethod
    def create_flink_security_group(scope, id, vpc, description="Security group for Flink to connect to MSK"):
        """
        Creates a security group for Flink application.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the security group
            vpc: The VPC to create the security group in
            description: Description for the security group
            
        Returns:
            The created security group
        """
        security_group = ec2.SecurityGroup(
            scope,
            id,
            vpc=vpc,
            description=description,
            allow_all_outbound=True,
        )

        # Allow outbound traffic from Flink to MSK
        security_group.add_egress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(9098),
            description="Allow outbound traffic to MSK IAM port",
        )

        # Allow outbound traffic to S3 and Lambda (HTTPS)
        security_group.add_egress_rule(
            peer=ec2.Peer.any_ipv4(),
            connection=ec2.Port.tcp(443),
            description="Allow outbound traffic to S3 and Lambda via HTTPS",
        )
        
        return security_group
    
    @staticmethod
    def create_flink_log_group(scope, id, log_group_name, retention_days=logs.RetentionDays.ONE_WEEK):
        """
        Creates a CloudWatch log group for Flink application.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the log group
            log_group_name: The name of the log group
            retention_days: Log retention period
            
        Returns:
            The created log group
        """
        return logs.LogGroup(
            scope,
            id,
            log_group_name=log_group_name,
            retention=retention_days,
            removal_policy=RemovalPolicy.DESTROY,
        )
    
    @staticmethod
    def create_flink_role(scope, id, account_id, region, application_name, msk_cluster_arn):
        """
        Creates an IAM role for Flink application with MSK access.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the role
            account_id: AWS account ID
            region: AWS region
            application_name: Name of the Flink application
            msk_cluster_arn: ARN of the MSK cluster
            
        Returns:
            The created IAM role
        """
        role = iam.Role(
            scope,
            id,
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal(
                    "kinesisanalytics.amazonaws.com",
                    conditions={
                        "StringEquals": {"aws:SourceAccount": account_id},
                        "ArnEquals": {
                            "aws:SourceArn": f'arn:aws:kinesisanalytics:{region}:{account_id}:application/{application_name}'
                        },
                    },
                ),
            ),
        )
        
        # Add MSK cluster access policies
        role.add_to_policy(MSKPolicyFactory.get_cluster_access_policy(msk_cluster_arn))
        role.add_to_policy(MSKPolicyFactory.get_topic_admin_policy(msk_cluster_arn))
        role.add_to_policy(MSKPolicyFactory.get_consumer_group_policy(msk_cluster_arn))
        
        return role
    
    @staticmethod
    def create_flink_application(scope, id, application_name, artifact_bucket, jar_file_name, 
                                log_group, role, vpc, security_groups, bootstrap_brokers, 
                                input_topic, output_topic, runtime=flink.Runtime.FLINK_1_20):
        """
        LEGACY: Creates a Java Flink application.
        
        DEPRECATED: Use create_pyflink_application() for new projects.
        This method is retained for migration purposes only.

        Args:
            scope: The CDK construct scope
            id: The ID for the application
            application_name: Name of the Flink application
            artifact_bucket: S3 bucket containing the Flink JAR
            jar_file_name: Name of the JAR file
            log_group: CloudWatch log group
            role: IAM role for the application
            vpc: VPC for the application
            security_groups: Security groups for the application
            bootstrap_brokers: MSK bootstrap brokers
            input_topic: Input Kafka topic
            output_topic: Output Kafka topic
            runtime: Flink runtime version
            
        Returns:
            The created Flink application
        """
        return flink.Application(
            scope,
            id,
            code=flink.ApplicationCode.from_bucket(
                artifact_bucket,
                jar_file_name,
            ),
            application_name=application_name,
            runtime=runtime,
            log_group=log_group,
            log_level=flink.LogLevel.INFO,
            role=role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=security_groups,
            property_groups={
                "FlinkApplicationProperties": {
                    "source": "kafka-json",
                    "bootstrap.servers": bootstrap_brokers,
                    "input.topic": input_topic,
                    "sink": "kafka",
                    "output.topic": output_topic,
                    "kafka.authentication": "IAM",
                },
            },
        )
    
    @staticmethod
    def create_pyflink_application(scope, id, application_name, artifact_bucket, python_script_path,
                                   log_group, role, vpc, security_groups, bootstrap_brokers,
                                   input_topic, output_topic, parallelism=4, runtime=flink.Runtime.FLINK_1_20):
        """
        Creates a PyFlink (Python-based) Flink application.
        
        PyFlink provides:
        - Faster development (no compilation cycle)
        - Integration with Python ecosystem (NumPy, scikit-learn, boto3)
        - Feature parity with Java Flink 1.20+ (exactly-once, windowing, state)
        - AWS Managed Flink native support
        
        The Python script is packaged with dependencies and uploaded to S3.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the application
            application_name: Name of the Flink application
            artifact_bucket: S3 bucket for Python artifacts
            python_script_path: Path to Python script in local workspace
                               (e.g., "flink_pyflink_app/order_processor.py")
            log_group: CloudWatch log group
            role: IAM role for the application
            vpc: VPC for the application
            security_groups: Security groups for the application
            bootstrap_brokers: MSK bootstrap brokers
            input_topic: Input Kafka topic
            output_topic: Output Kafka topic
            parallelism: Degree of parallelism (default 4, match Kafka partitions)
            runtime: Flink runtime version (FLINK_1_20 recommended)
            
        Returns:
            The created Flink application
            
        Design Notes:
            - Python script is asset-ified (CDK packages it automatically)
            - Dependencies from requirements.txt are installed at runtime
            - Configuration passed via CloudWatch Application Config (PropertyGroups)
            - State backend is RocksDB + S3 (configured by Managed Flink)
        """
        # Package Python artifacts as CDK asset
        # This automatically zips the flink_pyflink_app directory and uploads to S3
        python_asset = s3_assets.Asset(
            scope,
            f"{id}PythonAsset",
            path=python_script_path,
            # Staging directory for CDK asset packaging
            asset_hash_type="source",
        )
        
        # Create Flink application using Python code from S3
        # PyFlink 1.20 natively supports Python applications in Managed Flink
        return flink.Application(
            scope,
            id,
            code=flink.ApplicationCode.from_asset(
                python_asset,
                # Entrypoint: the Python script to run
                entry_point="order_processor.py",
            ),
            application_name=application_name,
            runtime=runtime,
            log_group=log_group,
            log_level=flink.LogLevel.INFO,
            role=role,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=security_groups,
            # Configuration passed to Python application via environment
            property_groups={
                "FlinkApplicationProperties": {
                    "bootstrap.servers": bootstrap_brokers,
                    "input.topic": input_topic,
                    "output.topic": output_topic,
                    "dlq.topic": f"{input_topic.replace('.raw', '.dlq')}",
                    "metrics.topic": f"{input_topic.replace('.raw', '.aggregations')}",
                    "kafka.authentication": "IAM",
                    "parallelism": str(parallelism),
                    "checkpoint.interval": "60000",  # 60 seconds
                    "watermark.allowed_lateness": "600000",  # 10 minutes
                },
            },
        )

    
    @staticmethod
    def grant_bucket_permissions(flink_app, buckets):
        """
        Grants read/write permissions to S3 buckets for the Flink application.
        
        Args:
            flink_app: The Flink application
            buckets: List of S3 buckets to grant access to
        """
        for bucket in buckets:
            bucket.grant_read_write(flink_app)
    
    @staticmethod
    def grant_dynamodb_permissions(role, tables):
        """
        Grants read/write permissions to DynamoDB tables for the Flink role.
        
        Args:
            role: The Flink IAM role
            tables: List of DynamoDB tables to grant access to
        """
        for table in tables:
            table.grant_read_write_data(role)
    
    @staticmethod
    def output_flink_info(scope, flink_app, log_group):
        """
        Creates CloudFormation outputs for Flink application information.
        
        Args:
            scope: The CDK construct scope
            flink_app: The Flink application
            log_group: The CloudWatch log group
        """
        # Output the Flink application ARN
        CfnOutput(
            scope,
            "FlinkApplicationArn",
            value=flink_app.application_arn,
            description="ARN of the Flink application",
        )

        # Output the Flink log group ARN
        CfnOutput(
            scope,
            "FlinkLogGroupArn",
            value=log_group.log_group_arn,
            description="ARN of the Flink log group",
        )
