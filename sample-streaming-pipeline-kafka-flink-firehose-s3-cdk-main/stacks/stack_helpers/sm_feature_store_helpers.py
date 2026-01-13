## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import (
    RemovalPolicy,
    Duration,
    aws_iam as iam,
    aws_s3 as s3,
    aws_sagemaker as sagemaker,
    aws_kms as kms,
    aws_lambda as _lambda,
    CfnOutput,
    aws_ec2 as ec2,
)
import aws_cdk as cdk
from constructs import Construct
from aws_cdk.aws_lambda_event_sources import ManagedKafkaEventSource
from typing import List

from .helper import get_topic_name, get_group_name
from .iam_helpers import MSKPolicyFactory


class SageMakerFactory:
    """Factory class for creating SageMaker Feature Store related resources."""

    @staticmethod
    def create_feature_store_kms_key(
        scope: Construct,
        id: str,
        description: str = "KMS key for SageMaker Feature Store encryption"
    ) -> kms.Key:
        """Create KMS key for Feature Store encryption."""
        return kms.Key(
            scope,
            id,
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.DESTROY,
            description=description
        )

    @staticmethod
    def create_feature_store_role(
        scope: Construct,
        id: str,
        feature_store_bucket: s3.Bucket,
        feature_store_key: kms.Key,
        feature_group_name: str,
        partition: str,
        region: str,
        account: str,
    ) -> iam.Role:
        """Create IAM role for Feature Store with required permissions."""
        
        role = iam.Role(
            scope,
            id,
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal("sagemaker.amazonaws.com")
            ),
            description="IAM role for SageMaker Feature Store",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSageMakerFeatureStoreAccess")
            ]
        )

        # Add bucket policy to allow both SageMaker service and the feature store role
        feature_store_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                    "s3:GetBucketAcl",
                    "s3:PutObjectAcl"
                ],
                resources=[
                    feature_store_bucket.bucket_arn,
                    f"{feature_store_bucket.bucket_arn}/*"
                ],
                principals=[
                    iam.ServicePrincipal("sagemaker.amazonaws.com"),
                    iam.ArnPrincipal(role.role_arn)
                ]
            )
        )

        # Grant S3 permissions directly to the role
        feature_store_bucket.grant_read_write(role)
        
        # Add explicit S3 permissions
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:GetBucketAcl",
                    "s3:PutObjectAcl",
                    "s3:ListBucket",
                ],
                resources=[
                    feature_store_bucket.bucket_arn,
                    f"{feature_store_bucket.bucket_arn}/*",
                ],
            )
        )

        # Add KMS permissions
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:DescribeKey",
                    "kms:CreateGrant",
                    "kms:RetireGrant",
                    "kms:ReEncryptFrom",
                    "kms:ReEncryptTo",
                    "kms:GenerateDataKey",
                    "kms:ListAliases",
                    "kms:ListGrants",
                    "kms:RevokeGrant"
                ],
                resources=[feature_store_key.key_arn],
            )
        )
        
        # Add SageMaker Feature Store permissions
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sagemaker:PutRecord"],
                resources=[
                    f"arn:{partition}:sagemaker:{region}:{account}:feature-group/{feature_group_name}",
                ],
            ),
        )

        # Grant KMS permissions to the role
        feature_store_key.grant_encrypt_decrypt(role)

        return role

    @staticmethod
    def create_feature_group(
        scope: Construct,
        id: str,
        feature_group_name: str,
        feature_store_bucket: s3.Bucket,
        feature_store_key: kms.Key,
        feature_store_role: iam.Role,
    ) -> sagemaker.CfnFeatureGroup:
        """Create SageMaker Feature Group for stock data."""
        
        feature_group = sagemaker.CfnFeatureGroup(
            scope,
            id,
            feature_group_name=feature_group_name,
            record_identifier_feature_name="id",
            event_time_feature_name="event_time",
            feature_definitions=[
                sagemaker.CfnFeatureGroup.FeatureDefinitionProperty(
                    feature_name="id",
                    feature_type="String"
                ),
                sagemaker.CfnFeatureGroup.FeatureDefinitionProperty(
                    feature_name="ticker",
                    feature_type="String"
                ),
                sagemaker.CfnFeatureGroup.FeatureDefinitionProperty(
                    feature_name="price",
                    feature_type="String"
                ),
                sagemaker.CfnFeatureGroup.FeatureDefinitionProperty(
                    feature_name="datetime",
                    feature_type="String"
                ),
                sagemaker.CfnFeatureGroup.FeatureDefinitionProperty(
                    feature_name="event_time",
                    feature_type="String"
                )
            ],
            offline_store_config={
                "S3StorageConfig": {
                    "S3Uri": f"s3://{feature_store_bucket.bucket_name}/sm-features/",
                    "KmsKeyId": feature_store_key.key_arn
                },
            },
            online_store_config={
                "EnableOnlineStore": True,
                "SecurityConfig": {
                    "KmsKeyId": feature_store_key.key_arn
                }
            },
            role_arn=feature_store_role.role_arn,
            description="Feature group for stock price data"
        )

        # Add dependencies
        feature_group.node.add_dependency(feature_store_bucket)
        feature_group.node.add_dependency(feature_store_role)

        return feature_group

    @staticmethod
    def create_feature_store_lambda(
        scope: Construct,
        id: str,
        vpc: ec2.Vpc,
        security_group: ec2.SecurityGroup,
        feature_group_name: str,
        msk_cluster_arn: str,
        output_topic: str,
        consumer_group_id: str,
        batch_size: int,
        feature_store_key: kms.Key,
        partition: str,
        region: str,
        account: str,
    ) -> _lambda.Function:
        """Create Lambda function for Feature Store integration."""
        
        lambda_function = _lambda.Function(
            scope,
            id,
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="feature_store_lambda.handler",
            code=_lambda.Code.from_asset("lambda/feature_store_lambda"),
            timeout=Duration.seconds(60),
            memory_size=256,
            vpc=vpc,
            security_groups=[security_group],
            environment={
                "FEATURE_GROUP_NAME": feature_group_name
            }
        )

        # Add MSK permissions
        SageMakerFactory._add_msk_permissions(lambda_function, msk_cluster_arn)
        
        # Add Feature Store permissions
        SageMakerFactory._add_feature_store_permissions(
            lambda_function, feature_group_name, partition, region, account
        )
        
        # Add KMS permissions
        SageMakerFactory._add_kms_permissions(lambda_function, feature_store_key)
        
        # Attach Kafka event source
        lambda_function.add_event_source(
            ManagedKafkaEventSource(
                cluster_arn=msk_cluster_arn,
                topic=output_topic,
                batch_size=batch_size,
                consumer_group_id=consumer_group_id,
                starting_position=_lambda.StartingPosition.TRIM_HORIZON,
            )
        )

        return lambda_function

    @staticmethod
    def _add_msk_permissions(lambda_function: _lambda.Function, msk_cluster_arn: str) -> None:
        """Add MSK permissions to Lambda function."""
        lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:Connect",
                    "kafka-cluster:DescribeClusterDynamicConfiguration",
                ],
                resources=[msk_cluster_arn],
            )
        )

        lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:DescribeTopic",
                    "kafka-cluster:ReadData",
                ],
                resources=[get_topic_name(kafka_cluster_arn=msk_cluster_arn, topic_name="*")],
            )
        )

        lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "kafka-cluster:DescribeGroup",
                    "kafka-cluster:AlterGroup",
                    "kafka-cluster:ReadGroup",
                ],
                resources=[get_group_name(kafka_cluster_arn=msk_cluster_arn, group_name="*")],
            )
        )

    @staticmethod
    def _add_feature_store_permissions(
        lambda_function: _lambda.Function, 
        feature_group_name: str, 
        partition: str, 
        region: str, 
        account: str
    ) -> None:
        """Add Feature Store permissions to Lambda function."""
        lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "sagemaker:PutRecord",
                    "sagemaker:GetRecord",
                    "sagemaker:DeleteRecord",
                    "sagemaker:DescribeFeatureGroup"
                ],
                resources=[
                    f"arn:{partition}:sagemaker:{region}:{account}:feature-group/{feature_group_name}",
                ],
            )
        )

    @staticmethod
    def _add_kms_permissions(lambda_function: _lambda.Function, feature_store_key: kms.Key) -> None:
        """Add KMS permissions to Lambda function."""
        lambda_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:DescribeKey",
                    "kms:GenerateDataKey",
                    "kms:ReEncryptFrom",
                    "kms:ReEncryptTo"
                ],
                resources=[feature_store_key.key_arn],
            )
        )

    @staticmethod
    def output_feature_store_info(
        scope: Construct,
        feature_store_bucket: s3.Bucket,
        feature_group_name: str,
        feature_store_lambda: _lambda.Function,
    ) -> None:
        """Create CloudFormation outputs for Feature Store resources."""
        
        CfnOutput(
            scope,
            "OfflineStoreBucketOutput",
            value=feature_store_bucket.bucket_name,
            description="S3 bucket for Feature Store offline storage",
            export_name="FeatureStoreOfflineBucket"
        )

        CfnOutput(
            scope,
            "StockFeatureGroupOutput",
            value=feature_group_name,
            description="Stock Price Feature Group name",
            export_name="StockFeatureGroup"
        )
        
        CfnOutput(
            scope,
            "FeatureStoreLambdaOutput",
            value=feature_store_lambda.function_arn,
            description="Feature Store Lambda function ARN",
            export_name="FeatureStoreLambda"
        )
        
        CfnOutput(
            scope,
            "FeatureStoreOnlineStoreOutput",
            value="Enabled",
            description="Feature Store Online Store Status",
            export_name="FeatureStoreOnlineStore"
        )
