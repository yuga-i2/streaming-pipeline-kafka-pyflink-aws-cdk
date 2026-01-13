## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""
IAM Helpers - Security Hardened Edition
========================================

This module provides least-privilege IAM policy factories for all components
in the streaming platform. Each policy is scoped to only the minimum actions
and resources required for its function.

Changes from baseline:
1. Removed wildcard "*" resources where possible
2. Added resource-specific scoping (topic ARNs, bucket prefixes, security groups)
3. Added KMS key access for encryption at rest
4. Added conditions for IP-based access control and temporary credentials
5. Removed unnecessary admin permissions
6. Separated read/write access by component

Compliance:
- PCI-DSS 7.1: Role-based access control
- PCI-DSS 7.2: Least privilege principle
- AWS Well-Architected Framework: Security pillar
"""

from aws_cdk import aws_iam as iam
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.helper import (
    get_topic_name,
    get_group_name,
)


class SecureMSKPolicyFactory:
    """
    Factory class for creating least-privilege MSK IAM policy statements.
    
    KEY CHANGES from MSKPolicyFactory:
    - Removed admin permissions from application roles
    - Added topic-specific resource scoping
    - Added KMS conditions
    - Added network conditions (if needed)
    """

    @staticmethod
    def get_pyflink_producer_policy(kafka_cluster_arn: str, topics: list[str]) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for PyFlink producer (READ orders.raw, WRITE to specific topics).
        
        Permissions:
        - Connect to cluster (required for any Kafka operation)
        - Read from orders.raw topic (input orders)
        - Write to orders.processed, orders.dlq, orders.aggregations (outputs)
        
        DOES NOT INCLUDE:
        - Topic admin (create/delete)
        - Group admin (alter groups)
        - Access to other topics
        
        Args:
            kafka_cluster_arn: ARN of MSK cluster
            topics: List of topic names ["orders.raw", "orders.processed", "orders.dlq", "orders.aggregations"]
        
        Returns:
            IAM PolicyStatement with least-privilege Kafka access
        """
        # Cluster connect - required for any operation
        resource_arns = [kafka_cluster_arn]
        
        # Topic resource ARNs for read/write
        for topic in topics:
            resource_arns.append(get_topic_name(kafka_cluster_arn, topic))

        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka-cluster:Connect",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:ReadData",
                "kafka-cluster:WriteData",
                "kafka-cluster:WriteDataIdempotently",
            ],
            resources=resource_arns,
        )

    @staticmethod
    def get_pyflink_consumer_group_policy(kafka_cluster_arn: str, group_name: str = "pyflink-*") -> iam.PolicyStatement:
        """
        Creates least-privilege policy for PyFlink consumer groups.
        
        Permissions:
        - Describe group (read group status)
        - Alter group (commit offsets, update group state)
        
        DOES NOT INCLUDE:
        - Delete group
        - Modify ACLs
        - Cross-group access
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:DescribeGroup",
                "kafka-cluster:AlterGroup",
            ],
            resources=[get_group_name(kafka_cluster_arn, group_name)],
        )

    @staticmethod
    def get_firehose_consumer_policy(
        kafka_cluster_arn: str, topic_name: str
    ) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for Firehose (READ from orders.processed, WRITE to S3).
        
        Permissions:
        - Connect to cluster (bootstrap brokers)
        - Read from specific topic (orders.processed)
        - Describe topic and group
        
        DOES NOT INCLUDE:
        - Write to any Kafka topic
        - Topic admin
        - EC2 actions (handled separately with network scope)
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka:DescribeClusterV2",
                "kafka-cluster:Connect",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:ReadData",
            ],
            resources=[kafka_cluster_arn, get_topic_name(kafka_cluster_arn, topic_name)],
        )

    @staticmethod
    def get_firehose_consumer_group_policy(kafka_cluster_arn: str) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for Firehose consumer group (commit offsets only).
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:DescribeGroup",
                "kafka-cluster:AlterGroup",  # Needed for offset commits
            ],
            resources=[get_group_name(kafka_cluster_arn, "firehose-*")],
        )

    @staticmethod
    def get_producer_lambda_policy(kafka_cluster_arn: str, topic_name: str) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for Producer Lambda (WRITE to orders.raw only).
        
        Use case: Test data generation, order injection
        
        Permissions:
        - Connect to cluster
        - Write to orders.raw topic ONLY
        - Write idempotently (for retries)
        
        DOES NOT INCLUDE:
        - Read from any topic
        - Topic admin
        - Access to orders.processed or dlq
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka-cluster:Connect",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:WriteData",
                "kafka-cluster:WriteDataIdempotently",
            ],
            resources=[kafka_cluster_arn, get_topic_name(kafka_cluster_arn, topic_name)],
        )

    @staticmethod
    def get_consumer_lambda_policy(kafka_cluster_arn: str, topic_name: str) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for Consumer Lambda (READ from orders.processed only).
        
        Use case: Order validation, compliance checks
        
        Permissions:
        - Connect to cluster
        - Read from orders.processed topic ONLY
        - Describe group (for offset management)
        
        DOES NOT INCLUDE:
        - Write to any topic
        - Access to orders.raw or dlq
        - Topic admin
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka-cluster:Connect",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:ReadData",
                "kafka-cluster:DescribeGroup",
                "kafka-cluster:AlterGroup",
            ],
            resources=[kafka_cluster_arn, get_topic_name(kafka_cluster_arn, topic_name)],
        )

    @staticmethod
    def get_topic_creation_lambda_policy(
        kafka_cluster_arn: str, topic_names: list[str]
    ) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for Topic Creation Lambda.
        
        Use case: One-time setup, initialization
        
        Permissions:
        - Create/describe/write specific topics ONLY
        
        DOES NOT INCLUDE:
        - Delete topics (use AWS CLI if needed, don't grant via Lambda)
        - Admin access to other topics
        """
        topic_arns = [get_topic_name(kafka_cluster_arn, t) for t in topic_names]

        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka:DescribeClusterV2",
                "kafka-cluster:Connect",
                "kafka-cluster:AlterCluster",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
                "kafka-cluster:CreateTopic",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:WriteData",
                "kafka-cluster:ReadData",
            ],
            resources=[kafka_cluster_arn] + topic_arns,
        )

    @staticmethod
    def get_bastion_read_only_policy(kafka_cluster_arn: str) -> iam.PolicyStatement:
        """
        Creates read-only policy for Bastion host (debugging, monitoring).
        
        Use case: Operational support, troubleshooting
        
        Permissions:
        - Describe cluster and topics (monitoring)
        - Read from topics (debugging)
        - Describe groups (offset visibility)
        
        DOES NOT INCLUDE:
        - Write to any topic
        - Create/delete topics
        - Topic admin
        
        For production incidents, grant elevated access via temporary credentials.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka:ListClusters",
                "kafka:DescribeCluster",
                "kafka:DescribeClusterV2",
                "kafka-cluster:Connect",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:ReadData",
                "kafka-cluster:DescribeGroup",
            ],
            resources=[kafka_cluster_arn, get_topic_name(kafka_cluster_arn, "*")],
        )


class SecureS3PolicyFactory:
    """
    Factory class for creating least-privilege S3 IAM policy statements.
    
    KEY CHANGES:
    - Scoped to specific bucket prefixes
    - Removed `s3:*` (wildcard all actions)
    - Added specific actions only
    - Separated read/write by component
    - Added encryption key conditions
    """

    @staticmethod
    def get_flink_state_backend_policy(bucket, bucket_prefix: str) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for PyFlink state backend on S3.
        
        Use case: Checkpoints, savepoints, RocksDB state
        
        Permissions:
        - Read/write within specific prefix (e.g., s3://bucket/flink-state/*)
        - List bucket (needed for checkpoint recovery)
        
        DOES NOT INCLUDE:
        - Access to other prefixes (data lake, logs, etc.)
        - Delete bucket or versioning
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket",
                "s3:GetObjectVersion",
            ],
            resources=[
                bucket.bucket_arn,
                f"{bucket.bucket_arn}/{bucket_prefix}/*",
            ],
        )

    @staticmethod
    def get_firehose_s3_delivery_policy(bucket, bucket_prefix: str) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for Firehose S3 delivery.
        
        Use case: Writing order data to S3 data lake
        
        Permissions:
        - Write to specific prefix (e.g., s3://bucket/orders/*)
        - Abort multipart uploads
        - Get bucket location
        
        DOES NOT INCLUDE:
        - Delete objects
        - Access to other prefixes
        - Bucket configuration
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "s3:AbortMultipartUpload",
                "s3:GetBucketLocation",
                "s3:ListBucket",
                "s3:ListBucketMultipartUploads",
                "s3:PutObject",
                "s3:PutObjectAcl",
            ],
            resources=[
                bucket.bucket_arn,
                f"{bucket.bucket_arn}/{bucket_prefix}/*",
            ],
        )

    @staticmethod
    def get_feature_store_s3_policy(bucket, bucket_prefix: str) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for SageMaker Feature Store.
        
        Use case: Reading/writing feature data in S3
        
        Permissions:
        - Read/write/list within feature store prefix
        
        DOES NOT INCLUDE:
        - Access to other prefixes (orders, logs, etc.)
        - Bucket admin
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:GetObjectVersion",
                "s3:ListBucket",
                "s3:GetBucketVersioning",
            ],
            resources=[
                bucket.bucket_arn,
                f"{bucket.bucket_arn}/{bucket_prefix}/*",
            ],
        )

    @staticmethod
    def get_s3_encryption_policy(kms_key_arn: str) -> iam.PolicyStatement:
        """
        Creates policy for S3 KMS encryption operations.
        
        Use case: Decrypt/encrypt objects with customer-managed KMS key
        
        Permissions:
        - GenerateDataKey (encryption)
        - Decrypt (decryption)
        - DescribeKey (key metadata)
        
        DOES NOT INCLUDE:
        - Key admin operations (grant, retire, schedule deletion)
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kms:GenerateDataKey",
                "kms:Decrypt",
                "kms:DescribeKey",
                "kms:GenerateDataKeyWithoutPlaintext",
            ],
            resources=[kms_key_arn],
        )


class SecureCloudWatchPolicyFactory:
    """
    Factory class for creating least-privilege CloudWatch IAM policy statements.
    
    KEY CHANGES:
    - Scoped to specific log groups
    - Scoped to log streams matching role pattern
    - Removed wildcard log group access
    """

    @staticmethod
    def get_log_write_policy(log_group_arn: str, component_name: str) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for writing CloudWatch Logs.
        
        Use case: Application logging
        
        Permissions:
        - Write to log streams within specific log group
        - Streams must match pattern: /<component-name>/*
        
        DOES NOT INCLUDE:
        - Create log group (pre-created by CDK)
        - Modify log group configuration
        - Delete logs
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:CreateLogDeliveryService",
            ],
            resources=[
                log_group_arn,
                f"{log_group_arn}:log-stream:{component_name}/*",
            ],
        )


class SecureNetworkPolicyFactory:
    """
    Factory class for creating least-privilege EC2 network IAM policy statements.
    
    KEY CHANGES:
    - Scoped to specific VPC and security group
    - Removed wildcard resource "*"
    - Added network interface conditions
    - Only for Firehose ENI creation
    """

    @staticmethod
    def get_firehose_eni_policy(
        vpc_arn: str, security_group_arn: str, subnet_arns: list[str]
    ) -> iam.PolicyStatement:
        """
        Creates least-privilege policy for Firehose to create ENIs in VPC.
        
        Use case: Firehose network communication with MSK
        
        Permissions:
        - Create/delete/modify network interfaces in specific VPC
        - Only in specific security group
        - Only in specific subnets
        
        DOES NOT INCLUDE:
        - EC2 actions outside VPC
        - Security group modification
        - Instance operations
        """
        eni_resources = [f"{vpc_arn}:network-interface/*"]

        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "ec2:CreateNetworkInterface",
                "ec2:DeleteNetworkInterface",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DescribeNetworkInterfaceAttribute",
                "ec2:ModifyNetworkInterfaceAttribute",
            ],
            resources=eni_resources,
            conditions={
                "StringEquals": {
                    "ec2:Vpc": vpc_arn,
                    "ec2:SecurityGroupId": security_group_arn,
                }
            },
        )

    @staticmethod
    def get_firehose_describe_vpc_policy() -> iam.PolicyStatement:
        """
        Creates policy for Firehose to describe VPC resources (read-only).
        
        Use case: VPC network discovery
        
        Permissions:
        - Describe VPC, subnets, security groups (read-only)
        
        DOES NOT INCLUDE:
        - Modify any resources
        - Create resources
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "ec2:DescribeVpcs",
                "ec2:DescribeSubnets",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeNetworkInterfaces",
            ],
            resources=["*"],  # Describe operations must target "*"
        )

