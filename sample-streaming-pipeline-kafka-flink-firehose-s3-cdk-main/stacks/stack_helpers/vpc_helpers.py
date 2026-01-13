## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import aws_ec2 as ec2

class VPCFactory:
    """
    Factory class for creating and configuring VPCs.
    """
    
    @staticmethod
    def create_vpc_with_flow_logs(
        scope,
        id,
        cidr_range,
        cidr_mask=24,
    ):
        """
        Creates a VPC with public and private subnets and flow logs.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the VPC
            cidr_range: The CIDR range for the VPC
            cidr_mask: The CIDR mask for the subnets
            
        Returns:
            The created VPC
        """
        public_subnet = ec2.SubnetConfiguration(
            name="PublicSubnet",
            subnet_type=ec2.SubnetType.PUBLIC,
            cidr_mask=cidr_mask,
        )
        
        private_subnet = ec2.SubnetConfiguration(
            name="PrivateSubnet",
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
            cidr_mask=cidr_mask,
        )
        
        vpc = ec2.Vpc(
            scope=scope,
            id=id,
            ip_addresses=ec2.IpAddresses.cidr(cidr_range),
            subnet_configuration=[public_subnet, private_subnet],
            flow_logs={
                "cloudwatch": ec2.FlowLogOptions(
                    destination=ec2.FlowLogDestination.to_cloud_watch_logs()
                )
            },
        )
        
        return vpc
