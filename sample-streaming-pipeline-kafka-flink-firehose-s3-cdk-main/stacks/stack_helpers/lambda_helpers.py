## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import (
    Duration,
    aws_lambda as _lambda,
    aws_ec2 as ec2,
)
from streaming_pipeline_kafka_flink_firehose_s3_cdk.stack_helpers.iam_helpers import MSKPolicyFactory

class LambdaFactory:
    """
    Factory class for creating Lambda functions with common configurations.
    """
    
    @staticmethod
    def create_kafka_lambda(
        scope,
        id,
        handler,
        code_path,
        vpc,
        security_group,
        layers,
        kafka_cluster_arn,
        environment={},
        timeout=Duration.seconds(60),
        memory_size=128,
        runtime=_lambda.Runtime.PYTHON_3_12,
        description=None,
        role_policies=None,
    ):
        """
        Creates a Lambda function with common configurations for Kafka integration.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the Lambda function
            handler: The handler function
            code_path: The path to the Lambda code
            vpc: The VPC to deploy the Lambda in
            security_group: The security group for the Lambda
            layers: The Lambda layers to use
            kafka_cluster_arn: The ARN of the MSK cluster
            environment: Environment variables for the Lambda
            timeout: The Lambda timeout
            memory_size: The Lambda memory size
            runtime: The Lambda runtime
            description: Description for the Lambda function
            role_policies: Additional IAM policies to add to the Lambda role
            
        Returns:
            The created Lambda function
        """
        # Create the Lambda function
        lambda_function = _lambda.Function(
            scope,
            id,
            runtime=runtime,
            handler=handler,
            timeout=timeout,
            memory_size=memory_size,
            code=_lambda.Code.from_asset(code_path),
            vpc=vpc,
            security_groups=[security_group],
            layers=layers,
            environment=environment,
            description=description,
        )
        
        # Add MSK permissions to Lambda role
        lambda_function.add_to_role_policy(MSKPolicyFactory.get_extended_cluster_access_policy(kafka_cluster_arn))
        
        # Add additional policies if provided
        if role_policies:
            for policy in role_policies:
                lambda_function.add_to_role_policy(policy)
        
        return lambda_function
    
    @staticmethod
    def create_producer_lambda(
        scope,
        id,
        code_path,
        vpc,
        security_group,
        layers,
        kafka_cluster_arn,
        topic_name,
        environment={},
        timeout=Duration.seconds(60),
    ):
        """
        Creates a Lambda function specifically configured as a Kafka producer.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the Lambda function
            code_path: The path to the Lambda code
            vpc: The VPC to deploy the Lambda in
            security_group: The security group for the Lambda
            layers: The Lambda layers to use
            kafka_cluster_arn: The ARN of the MSK cluster
            topic_name: The name of the Kafka topic
            environment: Additional environment variables for the Lambda
            timeout: The Lambda timeout
            memory_size: The Lambda memory size
            
        Returns:
            The created Lambda function
        """
        # Merge environment variables
        env_vars = {
            "MSK_CLUSTER_ARN": kafka_cluster_arn,
            "INPUT_TOPIC_NAME": topic_name,
            **environment
        }
        
        # Create the Lambda function
        producer_lambda = _lambda.Function(
            scope,
            id,
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="producer.handler",
            timeout=timeout,
            code=_lambda.Code.from_asset(code_path),
            vpc=vpc,
            security_groups=[security_group],
            layers=layers,
            environment=env_vars,
        )
        
        # Add MSK permissions to Lambda roles - using reusable policy methods
        producer_lambda.add_to_role_policy(
            MSKPolicyFactory.get_producer_cluster_policy(kafka_cluster_arn)
        )
        producer_lambda.add_to_role_policy(
            MSKPolicyFactory.get_producer_topic_policy(kafka_cluster_arn)
        )
        producer_lambda.add_to_role_policy(
            MSKPolicyFactory.get_producer_group_policy(kafka_cluster_arn)
        )
        
        return producer_lambda
    
    @staticmethod
    def create_topic_admin_lambda(
        scope,
        id,
        code_path,
        vpc,
        security_group,
        layers,
        kafka_cluster_arn,
        input_topic_name,
        output_topic_name,
        environment={},
        timeout=Duration.seconds(600),
        memory_size=512,
    ):
        """
        Creates a Lambda function specifically configured for Kafka topic administration.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the Lambda function
            code_path: The path to the Lambda code
            vpc: The VPC to deploy the Lambda in
            security_group: The security group for the Lambda
            layers: The Lambda layers to use
            kafka_cluster_arn: The ARN of the MSK cluster
            input_topic_name: The name of the input Kafka topic
            output_topic_name: The name of the output Kafka topic
            environment: Additional environment variables for the Lambda
            timeout: The Lambda timeout
            memory_size: The Lambda memory size
            
        Returns:
            The created Lambda function
        """
        # Merge environment variables
        env_vars = {
            "MSK_CLUSTER_ARN": kafka_cluster_arn,
            "INPUT_TOPIC_NAME": input_topic_name,
            "OUTPUT_TOPIC_NAME": output_topic_name,
            **environment
        }
        
        # Create topic creation Lambda
        create_topic_lambda = _lambda.Function(
            scope,
            id,
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="create_topic.handler",
            timeout=timeout,  # 10 minutes timeout for topic creation
            memory_size=memory_size,  # Increased memory for better performance
            code=_lambda.Code.from_asset(code_path),
            vpc=vpc,
            security_groups=[security_group],
            layers=layers,
            environment=env_vars,
            description="Lambda function to create Kafka topics after MSK cluster deployment",
        )

        # Add MSK permissions to topic creation Lambda - using reusable policy methods
        create_topic_lambda.add_to_role_policy(
            MSKPolicyFactory.get_topic_admin_cluster_policy(kafka_cluster_arn)
        )
        create_topic_lambda.add_to_role_policy(
            MSKPolicyFactory.get_topic_admin_topic_policy(kafka_cluster_arn)
        )
        create_topic_lambda.add_to_role_policy(
            MSKPolicyFactory.get_group_access_policy(kafka_cluster_arn)
        )
        
        return create_topic_lambda
