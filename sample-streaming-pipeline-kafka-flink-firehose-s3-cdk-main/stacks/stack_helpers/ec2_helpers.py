## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import (
    aws_ec2 as ec2,
    aws_iam as iam,
)

class EC2Factory:
    """
    Factory class for creating and configuring EC2 instances.
    """
    
    @staticmethod
    def create_bastion_host(
        scope,
        id,
        vpc,
        security_group,
        instance_type="t3.micro",
        subnet_selection=ec2.SubnetType.PRIVATE_WITH_EGRESS,
    ):
        """
        Creates an EC2 instance for use as a bastion host.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the instance
            vpc: The VPC to deploy the instance in
            security_group: The security group for the instance
            instance_type: The instance type to use
            subnet_selection: The subnet type to deploy the instance in
            
        Returns:
            The created EC2 instance
        """
        instance = ec2.Instance(
            scope,
            id,
            vpc=vpc,
            instance_type=ec2.InstanceType(instance_type),
            vpc_subnets=ec2.SubnetSelection(subnet_type=subnet_selection),
            security_group=security_group,
            machine_image=ec2.MachineImage.latest_amazon_linux2(),
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda", volume=ec2.BlockDeviceVolume.ebs(8, encrypted=True)
                )
            ],
        )
        
        # Add SSM managed policy for remote access
        instance.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")
        )
        
        return instance
    
    @staticmethod
    def add_kafka_client_user_data(instance, kafka_cluster_arn, region):
        """
        Adds user data to an EC2 instance to configure it as a Kafka client.
        
        Args:
            instance: The EC2 instance to add user data to
            kafka_cluster_arn: The ARN of the MSK cluster
            region: The AWS region
            
        Returns:
            The instance with user data added
        """
        instance.add_user_data(
            "yum update -y",
            "yum install -y java-11-amazon-corretto-headless",  # install a trusted JRE
            "cd /home/ec2-user/",
            "wget https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip",  # upgrade to AWS CLI v2 to get bootstrap information
            "wget https://github.com/aws/aws-msk-iam-auth/releases/download/v2.3.1/aws-msk-iam-auth-2.3.1-all.jar",
            "wget https://archive.apache.org/dist/kafka/2.8.1/kafka_2.12-2.8.1.tgz",
            "unzip awscli-exe-linux-x86_64.zip",
            "tar -xvf kafka_2.12-2.8.1.tgz",
            "./aws/install",
            "PATH=/usr/local/bin:$PATH",
            "source ~/.bash_profile",
            f'echo "TLS=$(aws kafka describe-cluster --cluster-arn {kafka_cluster_arn} --query "ClusterInfo.ZookeeperConnectString" --region {region})" >> /etc/environment',
            f'echo "ZK=$(aws kafka get-bootstrap-brokers --cluster-arn {kafka_cluster_arn} --query "BootstrapBrokerStringSaslIam" --region {region})" >> /etc/environment',
            'echo "CLASSPATH=/home/ec2-user/aws-msk-iam-auth-2.3.1-all.jar" >> /etc/environment',
            "cd kafka_2.12-2.8.1/bin/",
            'echo "security.protocol=SASL_SSL" >> client.properties',
            'echo "sasl.mechanism=AWS_MSK_IAM" >> client.properties',
            'echo "sasl.jaas.config=software.amazon.msk.auth.iam.IAMLoginModule required;" >> client.properties',
            'echo "sasl.client.callback.handler.class=software.amazon.msk.auth.iam.IAMClientCallbackHandler" >> client.properties',
        )
        
        return instance
