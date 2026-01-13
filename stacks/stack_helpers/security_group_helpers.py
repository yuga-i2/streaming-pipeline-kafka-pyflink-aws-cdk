## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import aws_ec2 as ec2

class SecurityGroupFactory:
    """
    Factory class for creating and configuring security groups.
    """
    
    @staticmethod
    def create_kafka_security_group(scope, id, vpc, description="MSK serverless demo kafka client security group"):
        """
        Creates a security group for the main Kafka cluster.
        
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
        )
        
        # Define list of ports that should communicate internally
        ports_list = [(2181, "Default Zookeeper"), (2182, "TLS Zookeeper"), (9098, "IAM Access")]
        
        # Allowing tcp ports to connect internally
        for port in ports_list:
            security_group.connections.allow_internally(
                ec2.Port.tcp(port=port[0]), description=port[1]
            )
        
        # For testing phase: Allow all traffic from the security group to itself
        security_group.connections.allow_from(
            other=security_group,
            port_range=ec2.Port.all_traffic(),
            description="Allow all traffic from the security group to itself",
        )
        
        return security_group
    
    @staticmethod
    def create_bastion_host_security_group(scope, id, vpc, description="kafka bastion host security group"):
        """
        Creates a security group for the bastion host.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the security group
            vpc: The VPC to create the security group in
            description: Description for the security group
            
        Returns:
            The created security group
        """
        return ec2.SecurityGroup(
            scope,
            id,
            vpc=vpc,
            description=description,
        )
    
    @staticmethod
    def create_lambda_security_group(scope, id, vpc, description="kafka lambda security group"):
        """
        Creates a security group for Lambda functions.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the security group
            vpc: The VPC to create the security group in
            description: Description for the security group
            
        Returns:
            The created security group
        """
        return ec2.SecurityGroup(
            scope,
            id,
            vpc=vpc,
            description=description,
        )
    
    @staticmethod
    def allow_security_group_connection(source_sg, target_sg, port=9098):
        """
        Allows connections from one security group to another on a specific port.
        
        Args:
            source_sg: The source security group
            target_sg: The target security group
            port: The port to allow connections on (default: 9098 for MSK)
        """
        target_sg.connections.allow_from(
            other=source_sg.connections, 
            port_range=ec2.Port.tcp(port),
            description=f"from MSKServerless{source_sg.node.id}:{port}"
        )
