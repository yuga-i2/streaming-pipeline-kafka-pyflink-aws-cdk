## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import (
    aws_iam as iam,
    aws_kinesisfirehose as firehose,
    ArnFormat,
    CfnOutput,
)
from constructs import Construct
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.helper import get_topic_name, get_group_name


class FirehoseFactory:
    """
    Factory class for creating Kinesis Data Firehose resources.
    """
    
    @staticmethod
    def create_firehose_role(
        scope: Construct,
        id: str,
        cluster_name: str,
        region: str,
        firehose_bucket,
        kafka_cluster_arn: str,
        output_topic_name: str,
        firehose_log_group_name: str,
    ) -> iam.Role:
        """
        Creates a Firehose service role with the necessary permissions.
        """
        firehose_role_policy_doc = iam.PolicyDocument()
        
        # S3 permissions
        firehose_role_policy_doc.add_statements(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[firehose_bucket.bucket_arn, 
                       f"{firehose_bucket.bucket_arn}/*"],
            actions=[
                "s3:AbortMultipartUpload",
                "s3:GetBucketLocation",
                "s3:GetObject",
                "s3:ListBucket",
                "s3:ListBucketMultipartUploads",
                "s3:PutObject"
            ]
        ))
        
        # CloudWatch Logs permissions
        firehose_role_policy_doc.add_statements(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[scope.format_arn(
                service="logs", 
                resource="log-group",
                resource_name=f"{firehose_log_group_name}:log-stream:*",
                arn_format=ArnFormat.COLON_RESOURCE_NAME
            )],
            actions=["logs:PutLogEvents"]
        ))
        
        # MSK cluster permissions
        firehose_role_policy_doc.add_statements(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[kafka_cluster_arn],
            actions=[
                "kafka:GetBootstrapBrokers",
                "kafka:DescribeCluster",
                "kafka:DescribeClusterV2",
                "kafka-cluster:Connect"
            ]
        ))
        
        # Kafka topic permissions
        firehose_role_policy_doc.add_statements(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[get_topic_name(kafka_cluster_arn=kafka_cluster_arn, topic_name=output_topic_name)],
            actions=[
                "kafka-cluster:DescribeTopic",
                "kafka-cluster:DescribeTopicDynamicConfiguration",
                "kafka-cluster:ReadData"
            ]
        ))
        
        # Kafka group permissions
        firehose_role_policy_doc.add_statements(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            resources=[get_group_name(kafka_cluster_arn=kafka_cluster_arn, group_name="*")],
            actions=[
                "kafka-cluster:DescribeGroup"
            ]
        ))

        # Add EC2 permissions to Firehose role
        firehose_role_policy_doc.add_statements(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "ec2:DescribeVpcs",
                "ec2:DescribeSubnets",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeNetworkInterfaces",
                "ec2:CreateNetworkInterface",
                "ec2:DeleteNetworkInterface",
                "ec2:DescribeNetworkInterfaceAttribute",
                "ec2:ModifyNetworkInterfaceAttribute"
            ],
            resources=["*"]
        ))

        firehose_role = iam.Role(
            scope,
            id,
            role_name=f"KinesisFirehoseServiceRole-{cluster_name}-{region}",
            assumed_by=iam.ServicePrincipal("firehose.amazonaws.com"),
            inline_policies={
                "firehose_role_policy": firehose_role_policy_doc
            }
        )
        
        return firehose_role
    
    @staticmethod
    def create_extended_s3_destination_config(
        firehose_bucket,
        firehose_role: iam.Role,
        firehose_buffering_hints: dict,
        firehose_log_group_name: str,
    ) -> firehose.CfnDeliveryStream.ExtendedS3DestinationConfigurationProperty:
        """
        Creates the extended S3 destination configuration for Firehose.
        """
        return firehose.CfnDeliveryStream.ExtendedS3DestinationConfigurationProperty(
            bucket_arn=firehose_bucket.bucket_arn,
            role_arn=firehose_role.role_arn,
            buffering_hints=firehose_buffering_hints,
            cloud_watch_logging_options={
                "enabled": True,
                "logGroupName": firehose_log_group_name,
                "logStreamName": "DestinationDelivery"
            },
            compression_format="UNCOMPRESSED",  # [GZIP | HADOOP_SNAPPY | Snappy | UNCOMPRESSED | ZIP]
            data_format_conversion_configuration={
                "enabled": False
            },
            processing_configuration={
                "enabled": False
            },
            # error_output_prefix="error-json/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/!{firehose:error-output-type}",
            # prefix="json-data/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
        )
    
    @staticmethod
    def create_firehose_delivery_stream(
        scope: Construct,
        id: str,
        delivery_stream_name: str,
        kafka_cluster_arn: str,
        output_topic_name: str,
        firehose_role: iam.Role,
        extended_s3_dest_config: firehose.CfnDeliveryStream.ExtendedS3DestinationConfigurationProperty,
    ) -> firehose.CfnDeliveryStream:
        """
        Creates a Kinesis Data Firehose delivery stream.
        """
        return firehose.CfnDeliveryStream(
            scope,
            id,
            delivery_stream_name=delivery_stream_name,
            delivery_stream_type="MSKAsSource",
            msk_source_configuration=firehose.CfnDeliveryStream.MSKSourceConfigurationProperty(
                authentication_configuration={
                    'connectivity': 'PRIVATE',  # [PRIVATE | PUBLIC]
                    'roleArn': firehose_role.role_arn,
                },
                msk_cluster_arn=kafka_cluster_arn,
                topic_name=output_topic_name
            ),
            extended_s3_destination_configuration=extended_s3_dest_config,
        )
    
    @staticmethod
    def output_firehose_info(
        scope: Construct,
        stack_name: str,
        firehose_bucket,
        firehose_delivery_stream: firehose.CfnDeliveryStream,
        firehose_role: iam.Role,
    ):
        """
        Creates CloudFormation outputs for Firehose resources.
        """
        CfnOutput(
            scope,
            'S3DestBucketName',
            value=firehose_bucket.bucket_name,
            export_name=f'{stack_name}-S3DestBucketName'
        )
        CfnOutput(
            scope,
            'S3DestBucketArn',
            value=firehose_delivery_stream.extended_s3_destination_configuration.bucket_arn,
            export_name=f'{stack_name}-S3DestBucketArn'
        )
        CfnOutput(
            scope,
            'FirehoseRoleArn',
            value=firehose_role.role_arn,
            export_name=f'{stack_name}-FirehoseRoleArn'
        )
        CfnOutput(
            scope,
            'MSKClusterArn',
            value=firehose_delivery_stream.msk_source_configuration.msk_cluster_arn,
            export_name=f'{stack_name}-MSKClusterArn'
        )
        CfnOutput(
            scope,
            'MSKAsSourceTopicName',
            value=firehose_delivery_stream.msk_source_configuration.topic_name,
            export_name=f'{stack_name}-MSKAsSourceTopicName'
        )
