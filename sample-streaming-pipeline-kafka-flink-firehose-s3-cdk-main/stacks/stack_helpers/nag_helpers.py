## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from cdk_nag import NagSuppressions

class NagSuppressionHelper:
    """
    Helper class for applying CDK Nag suppressions in a consistent way.
    """
    
    @staticmethod
    def suppress_lambda_role_policies(scope, resources, apply_to_children=True):
        """
        Applies common suppressions for Lambda role policies.
        
        Args:
            scope: The CDK construct scope
            resources: The resources to apply suppressions to
            apply_to_children: Whether to apply suppressions to child resources
        """
        NagSuppressions.add_resource_suppressions(
            resources,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "This code is for demo purposes. Using AWS managed policy, in production use custom policies.",
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "This code is for demo purposes. So granted access to all indices of S3 bucket and Kafka topics.",
                },
            ],
            apply_to_children=apply_to_children,
        )
    
    @staticmethod
    def suppress_lambda_runtime(scope, resources, apply_to_children=True):
        """
        Applies suppressions for Lambda runtime warnings.
        
        Args:
            scope: The CDK construct scope
            resources: The resources to apply suppressions to
            apply_to_children: Whether to apply suppressions to child resources
        """
        NagSuppressions.add_resource_suppressions(
            resources,
            suppressions=[
                {
                    "id": "AwsSolutions-L1",
                    "reason": "Lambda layer is compiled on python3.12 version so using Python 3.12 runtime on Lambda",
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "Using AWS managed policies AWSLambdaBasicExecutionRole and AWSLambdaVPCAccessExecutionRole for Lambda execution",
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "This code is for demo purposes. So granted access to all indices of Kafka.",
                },
            ],
            apply_to_children=apply_to_children,
        )
    
    @staticmethod
    def suppress_ec2_instance(scope, resources, apply_to_children=True):
        """
        Applies suppressions for EC2 instance warnings.
        
        Args:
            scope: The CDK construct scope
            resources: The resources to apply suppressions to
            apply_to_children: Whether to apply suppressions to child resources
        """
        NagSuppressions.add_resource_suppressions(
            resources,
            suppressions=[
                {
                    "id": "AwsSolutions-EC28",
                    "reason": "This code is for demo purposes so detailed monitoring is not enabled for the bastion host.",
                },
                {
                    "id": "AwsSolutions-EC29",
                    "reason": "This code is for demo purposes so termination protection is not enabled for the bastion host.",
                },
            ],
            apply_to_children=apply_to_children,
        )
    
    @staticmethod
    def suppress_custom_resource_provider(scope, path_prefix):
        """
        Applies suppressions for custom resource provider warnings.
        
        Args:
            scope: The CDK construct scope
            path_prefix: The path prefix for the custom resource provider
        """
        NagSuppressions.add_resource_suppressions_by_path(
            scope,
            path=f"{path_prefix}/TopicCreationProvider/framework-onEvent/ServiceRole/Resource",
            suppressions=[
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "Custom resource provider requires AWS managed policies for Lambda execution in VPC.",
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
                    ]
                }
            ]
        )
        
        NagSuppressions.add_resource_suppressions_by_path(
            scope,
            path=f"{path_prefix}/TopicCreationProvider/framework-onEvent/ServiceRole/DefaultPolicy/Resource",
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Custom resource provider needs wildcard permissions to invoke the Lambda function.",
                    "appliesTo": [
                        "Resource::<KafkaTopicCreateFunction395DA3FF.Arn>:*"
                    ]
                }
            ]
        )
        
        NagSuppressions.add_resource_suppressions_by_path(
            scope,
            path=f"{path_prefix}/TopicCreationProvider/framework-onEvent/Resource",
            suppressions=[
                {
                    "id": "AwsSolutions-L1",
                    "reason": "Custom resource provider framework uses a specific runtime version for compatibility."
                }
            ]
        )
    
    @staticmethod
    def suppress_s3_access_logs_bucket(scope, resources, apply_to_children=True):
        """
        Applies suppressions for S3 access logs bucket warnings.
        
        Args:
            scope: The CDK construct scope
            resources: The resources to apply suppressions to
            apply_to_children: Whether to apply suppressions to child resources
        """
        NagSuppressions.add_resource_suppressions(
            resources,
            suppressions=[
                {
                    "id": "AwsSolutions-S1",
                    "reason": "This is the access logs bucket itself, so it doesn't need server access logging enabled to avoid circular logging.",
                },
            ],
            apply_to_children=apply_to_children,
        )
    
    @staticmethod
    def suppress_flink_role(scope, resources, apply_to_children=True):
        """
        Applies suppressions for Flink role warnings.
        
        Args:
            scope: The CDK construct scope
            resources: The resources to apply suppressions to
            apply_to_children: Whether to apply suppressions to child resources
        """
        NagSuppressions.add_resource_suppressions(
            resources,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "This is for a demo, so Managed policy is used.",
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "This is for a demo, so wildcard permissions for Kafka topics/groups are used.",
                },
            ],
            apply_to_children=apply_to_children,
        )
    
    @staticmethod
    def suppress_firehose_role(scope, resources, apply_to_children=True):
        """
        Applies suppressions for Firehose role warnings.
        
        Args:
            scope: The CDK construct scope
            resources: The resources to apply suppressions to
            apply_to_children: Whether to apply suppressions to child resources
        """
        NagSuppressions.add_resource_suppressions(
            resources,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "This code uses more granular permissions but still needs access to all indices of S3 bucket for proper operation.",
                },
            ],
            apply_to_children=apply_to_children,
        )
    
    @staticmethod
    def suppress_firehose_delivery_stream(scope, resources, apply_to_children=True):
        """
        Applies suppressions for Firehose delivery stream warnings.
        
        Args:
            scope: The CDK construct scope
            resources: The resources to apply suppressions to
            apply_to_children: Whether to apply suppressions to child resources
        """
        NagSuppressions.add_resource_suppressions(
            resources,
            suppressions=[
                {
                    "id": "AwsSolutions-KDF1",
                    "reason": "This code is for demo purposes. Server-side encryption is not enabled for the Kinesis Data Firehose delivery stream.",
                },
            ],
            apply_to_children=apply_to_children,
        )
