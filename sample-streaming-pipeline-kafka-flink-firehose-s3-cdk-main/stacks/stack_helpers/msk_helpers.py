## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import (
    aws_msk as msk,
    aws_logs as logs,
    aws_ec2 as ec2,
    CfnOutput,
)
import json

class MSKFactory:
    """
    Factory class for creating and configuring MSK clusters.
    """
    
    @staticmethod
    def create_serverless_cluster(
        scope,
        id,
        cluster_name,
        vpc,
        security_group,
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
    ):
        """
        Creates a serverless MSK cluster.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the cluster
            cluster_name: The name of the cluster
            vpc: The VPC to deploy the cluster in
            security_group: The security group for the cluster
            subnet_type: The subnet type to deploy the cluster in
            
        Returns:
            The created MSK cluster
        """
        # Setting up log group with a retention of one day
        logs.LogGroup(scope, cluster_name + "BrokerLogs", retention=logs.RetentionDays.ONE_DAY)
        
        # Create the serverless cluster
        kafka_cluster = msk.CfnServerlessCluster(
            scope,
            id=id,
            cluster_name=cluster_name,
            vpc_configs=[
                msk.CfnServerlessCluster.VpcConfigProperty(
                    subnet_ids=vpc.select_subnets(
                        subnet_type=subnet_type
                    ).subnet_ids,
                    security_groups=[security_group.security_group_id],
                )
            ],
            client_authentication=msk.CfnServerlessCluster.ClientAuthenticationProperty(
                sasl=msk.CfnServerlessCluster.SaslProperty(
                    iam=msk.CfnServerlessCluster.IamProperty(enabled=True),
                )
            ),
        )
        
        return kafka_cluster
    
    @staticmethod
    def create_cluster_policy(scope, id, cluster_arn):
        """
        Creates a resource-based policy for an MSK cluster.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the policy
            cluster_arn: The ARN of the MSK cluster
            
        Returns:
            The created cluster policy
        """
        # Create a resource-based policy for the MSK cluster
        msk_resource_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "firehose.amazonaws.com"},
                    "Action": [
                        "kafka:CreateVpcConnection",
                        "kafka:GetBootstrapBrokers",
                        "kafka:DescribeClusterV2",
                    ],
                    "Resource": "${kafka_cluster_arn}",  # Will be replaced with actual ARN
                }
            ],
        }
        
        # Apply cluster policy with proper resource scope
        cfn_cluster_policy = msk.CfnClusterPolicy(
            scope,
            id,
            cluster_arn=cluster_arn,
            policy=json.loads(
                json.dumps(msk_resource_policy).replace("${kafka_cluster_arn}", cluster_arn)
            ),
        )
        
        return cfn_cluster_policy
    
    @staticmethod
    def output_cluster_info(scope, cluster_arn, cluster_name):
        """
        Creates CloudFormation outputs for MSK cluster information.
        
        Args:
            scope: The CDK construct scope
            cluster_arn: The ARN of the MSK cluster
            cluster_name: The name of the cluster
        """
        # Export the MSK cluster ARN for use in other stacks
        CfnOutput(
            scope,
            "MSKServerlessClusterArnOutput",
            value=cluster_arn,
            description="ARN of the MSK Serverless cluster",
            export_name="MSKServerlessClusterArn",
        )
