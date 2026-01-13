## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import aws_iam as iam
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.helper import get_topic_name, get_group_name

class MSKPolicyFactory:
    """
    Factory class for creating common MSK IAM policy statements.
    """
    
    @staticmethod
    def get_cluster_access_policy(kafka_cluster_arn):
        """
        Creates a policy statement for basic MSK cluster access.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:ListClusters",
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka-cluster:Connect",
                "kafka-cluster:AlterCluster",
            ],
            resources=[kafka_cluster_arn],
        )
    
    @staticmethod
    def get_extended_cluster_access_policy(kafka_cluster_arn):
        """
        Creates a policy statement for extended MSK cluster access (includes dynamic configuration).
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:ListClusters",
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka-cluster:Connect",
                "kafka-cluster:AlterCluster",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
            ],
            resources=[kafka_cluster_arn],
        )
    
    @staticmethod
    def get_topic_admin_policy(kafka_cluster_arn):
        """
        Creates a policy statement for administering Kafka topics.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:CreateTopic",
                "kafka-cluster:DeleteTopic",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:WriteData",
                "kafka-cluster:ReadData",
                "kafka-cluster:WriteDataIdempotently",
            ],
            resources=[get_topic_name(kafka_cluster_arn=kafka_cluster_arn, topic_name="*")],
        )
    
    @staticmethod
    def get_topic_producer_policy(kafka_cluster_arn):
        """
        Creates a policy statement for producing to Kafka topics.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:WriteData",
                "kafka-cluster:WriteDataIdempotently",
            ],
            resources=[get_topic_name(kafka_cluster_arn=kafka_cluster_arn, topic_name="*")],
        )
    
    @staticmethod
    def get_topic_consumer_policy(kafka_cluster_arn):
        """
        Creates a policy statement for consuming from Kafka topics.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:ReadData",
            ],
            resources=[get_topic_name(kafka_cluster_arn=kafka_cluster_arn, topic_name="*")],
        )
    
    @staticmethod
    def get_group_access_policy(kafka_cluster_arn):
        """
        Creates a policy statement for accessing consumer groups.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:DescribeGroup",
                "kafka-cluster:AlterGroup",
            ],
            resources=[get_group_name(kafka_cluster_arn=kafka_cluster_arn, group_name="*")],
        )
    
    @staticmethod
    def get_consumer_group_policy(kafka_cluster_arn):
        """
        Creates a policy statement for consumer group operations.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:DescribeGroup",
                "kafka-cluster:AlterGroup",
                "kafka-cluster:ReadGroup",
            ],
            resources=[get_group_name(kafka_cluster_arn=kafka_cluster_arn, group_name="*")],
        )
    
    @staticmethod
    def get_producer_cluster_policy(kafka_cluster_arn):
        """
        Creates a policy statement for producer cluster access (specific to producer Lambda).
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka-cluster:Connect",
                "kafka-cluster:DescribeCluster",
                "kafka-cluster:DescribeClusterDynamicConfiguration",
                "kafka-cluster:WriteDataIdempotently",
            ],
            resources=[kafka_cluster_arn],
        )
    
    @staticmethod
    def get_producer_topic_policy(kafka_cluster_arn):
        """
        Creates a policy statement for producer topic access.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:ReadData",
                "kafka-cluster:WriteData",
            ],
            resources=[get_topic_name(kafka_cluster_arn=kafka_cluster_arn, topic_name="*")],
        )
    
    @staticmethod
    def get_producer_group_policy(kafka_cluster_arn):
        """
        Creates a policy statement for producer group access.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka-cluster:DescribeGroup",
            ],
            resources=[get_group_name(kafka_cluster_arn=kafka_cluster_arn, group_name="*")],
        )
    
    @staticmethod
    def get_topic_admin_cluster_policy(kafka_cluster_arn):
        """
        Creates a policy statement for topic admin cluster access (specific to topic creation Lambda).
        """
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
            ],
            resources=[kafka_cluster_arn],
        )
    
    @staticmethod
    def get_topic_admin_topic_policy(kafka_cluster_arn):
        """
        Creates a policy statement for topic admin topic access.
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "kafka-cluster:CreateTopic",
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:WriteData",
                "kafka-cluster:ReadData",
            ],
            resources=[get_topic_name(kafka_cluster_arn=kafka_cluster_arn, topic_name="*")],
        )
