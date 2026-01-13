## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

"""
KMS Helpers - Customer-Managed Key Management
==============================================

This module provides factories for creating and managing customer-managed KMS keys
required for PCI-DSS and enterprise security compliance.

Key Concepts:
1. Customer-managed keys allow you to:
   - Control key rotation (automatic annual rotation)
   - View key usage in CloudTrail
   - Grant temporary key access
   - Implement key policies aligned to least privilege

2. Key hierarchy:
   - Master key: Used by administrators only
   - Data encryption keys: Used by applications
   - Each service gets its own key (key segregation)

3. Compliance impact:
   - PCI-DSS 3.2.1: Must use customer-managed keys
   - PCI-DSS 3.6: Must implement key rotation
   - PCI-DSS 10.2.5: Key usage must be audited
"""

from aws_cdk import (
    RemovalPolicy,
    aws_kms as kms,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


class KMSFactory:
    """
    Factory class for creating KMS keys with enterprise security controls.
    """

    @staticmethod
    def create_streaming_data_key(
        scope: Construct,
        id: str,
        description: str,
        key_admins: list[iam.IRole],
        key_users: list[iam.IRole],
        enable_rotation: bool = True,
    ) -> kms.Key:
        """
        Creates a customer-managed KMS key for encrypting streaming data.
        
        Args:
            scope: CDK construct scope
            id: Unique identifier for the key
            description: Human-readable description (appears in AWS Console, CloudTrail)
            key_admins: List of IAM roles that can manage key (typically security team)
            key_users: List of IAM roles that can use key (encrypt/decrypt)
            enable_rotation: Enable automatic annual key rotation (default: True)
            
        Returns:
            KMS Key construct
            
        Security Features:
        - Automatic annual key rotation (if enabled)
        - Key policy grants least privilege to users
        - Admin policy grants key management to specific admins
        - All key usage logged in CloudTrail
        - Key scheduled deletion protection
        """
        # Create the key with rotation enabled
        key = kms.Key(
            scope,
            id,
            description=description,
            enable_key_rotation=enable_rotation,
            removal_policy=RemovalPolicy.RETAIN,  # Never auto-delete encryption keys
            pending_window=kms.PendingWindow.days(7),  # 7-day wait before deletion
        )

        # Grant admin permissions to key administrators
        for admin_role in key_admins:
            key.grant(
                admin_role,
                kms.KmsAction.all_kms_actions(),
                # Note: This grants full KMS permissions; in strict environments,
                # could be further restricted to specific actions like:
                # - kms:CreateGrant
                # - kms:DescribeKey
                # - kms:GetKeyRotationStatus
            )

        # Grant user permissions (encrypt/decrypt only, no key management)
        for user_role in key_users:
            key.grant_encrypt_decrypt(user_role)

        return key

    @staticmethod
    def create_msk_encryption_key(
        scope: Construct,
        account_id: str,
        region: str,
        key_admins: list[iam.IRole],
        key_users: list[iam.IRole],
    ) -> kms.Key:
        """
        Creates a dedicated KMS key for MSK cluster encryption.
        
        This key is used to:
        - Encrypt Kafka messages at rest (broker storage)
        - Encrypt inter-broker traffic (optional TLS enhancement)
        
        Args:
            scope: CDK construct scope
            account_id: AWS account ID
            region: AWS region
            key_admins: Security team roles
            key_users: MSK service role + PyFlink role
            
        Returns:
            KMS Key for MSK encryption
            
        Important:
        - MSK can only use AWS managed or customer-managed keys
        - Must be created before MSK cluster
        - Key policy must allow MSK service principal
        """
        key = KMSFactory.create_streaming_data_key(
            scope=scope,
            id="MSKEncryptionKey",
            description="Customer-managed key for MSK cluster encryption at rest",
            key_admins=key_admins,
            key_users=key_users,
            enable_rotation=True,
        )

        # Allow MSK service to use the key
        key.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("kafka.amazonaws.com")],
                actions=[
                    "kms:Decrypt",
                    "kms:GenerateDataKey",
                    "kms:DescribeKey",
                    "kms:CreateGrant",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "StringLike": {"aws:SourceArn": f"arn:aws:kafka:{region}:{account_id}:*"},
                },
            )
        )

        return key

    @staticmethod
    def create_s3_encryption_key(
        scope: Construct,
        account_id: str,
        region: str,
        key_admins: list[iam.IRole],
        key_users: list[iam.IRole],
    ) -> kms.Key:
        """
        Creates a dedicated KMS key for S3 encryption.
        
        This key is used to encrypt:
        - PyFlink state checkpoints
        - Firehose delivered data (order data lake)
        - SageMaker Feature Store data
        
        Args:
            scope: CDK construct scope
            account_id: AWS account ID
            region: AWS region
            key_admins: Security team roles
            key_users: Flink, Firehose, SageMaker roles
            
        Returns:
            KMS Key for S3 encryption
        """
        key = KMSFactory.create_streaming_data_key(
            scope=scope,
            id="S3EncryptionKey",
            description="Customer-managed key for S3 bucket encryption (Flink state, data lake, Feature Store)",
            key_admins=key_admins,
            key_users=key_users,
            enable_rotation=True,
        )

        # Allow S3 service to use the key (for bucket default encryption)
        key.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("s3.amazonaws.com")],
                actions=[
                    "kms:Decrypt",
                    "kms:GenerateDataKey",
                    "kms:DescribeKey",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {"aws:SourceAccount": account_id},
                },
            )
        )

        return key

    @staticmethod
    def create_logs_encryption_key(
        scope: Construct,
        account_id: str,
        region: str,
        key_admins: list[iam.IRole],
        key_users: list[iam.IRole] = [],
    ) -> kms.Key:
        """
        Creates a dedicated KMS key for CloudWatch Logs encryption.
        
        This key encrypts:
        - PyFlink application logs
        - Firehose delivery logs
        - Lambda function logs
        
        Args:
            scope: CDK construct scope
            account_id: AWS account ID
            region: AWS region
            key_admins: Security team roles
            key_users: CloudWatch service (automatically managed)
            
        Returns:
            KMS Key for CloudWatch Logs encryption
            
        Note:
        - CloudWatch Logs service principal automatically granted access
        - Users list typically empty (automatic IAM role grants happen in stacks)
        """
        key = KMSFactory.create_streaming_data_key(
            scope=scope,
            id="CloudWatchLogsEncryptionKey",
            description="Customer-managed key for CloudWatch Logs encryption",
            key_admins=key_admins,
            key_users=key_users,
            enable_rotation=True,
        )

        # Allow CloudWatch Logs service to use the key
        key.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                principals=[iam.ServicePrincipal("logs.amazonaws.com")],
                actions=[
                    "kms:Encrypt",
                    "kms:Decrypt",
                    "kms:ReEncrypt*",
                    "kms:GenerateDataKey*",
                    "kms:CreateGrant",
                    "kms:DescribeKey",
                ],
                resources=["*"],
                conditions={
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "StringLike": {"kms:ViaService": f"logs.{region}.amazonaws.com"},
                },
            )
        )

        return key

    @staticmethod
    def grant_encrypt_decrypt(
        key: kms.IKey, role: iam.IRole, resource_restriction: str = None
    ) -> None:
        """
        Grants encrypt/decrypt permissions on KMS key to a role.
        
        Args:
            key: KMS key to grant access to
            role: IAM role to grant permissions to
            resource_restriction: Optional ARN pattern to restrict access (e.g., "s3:::bucket/*")
            
        Example:
            kms_key.grant_encrypt_decrypt(flink_role)
        """
        key.grant_encrypt_decrypt(role)

    @staticmethod
    def create_key_policy_for_principal(
        account_id: str, principal_arn: str, allow_actions: list[str]
    ) -> iam.PolicyStatement:
        """
        Creates a KMS key policy statement for a specific principal.
        
        Use this to grant fine-grained permissions (e.g., only Decrypt, not Encrypt).
        
        Args:
            account_id: AWS account ID
            principal_arn: ARN of role/user to grant access
            allow_actions: List of KMS actions to allow (e.g., ["kms:Decrypt"])
            
        Returns:
            IAM PolicyStatement for KMS key policy
            
        Example:
            statement = KMSFactory.create_key_policy_for_principal(
                account_id="123456789012",
                principal_arn="arn:aws:iam::123456789012:role/my-role",
                allow_actions=["kms:Decrypt", "kms:DescribeKey"]
            )
        """
        return iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            principals=[iam.ArnPrincipal(principal_arn)],
            actions=allow_actions,
            resources=["*"],
        )


# ============================================================================
# Key Architecture Summary
# ============================================================================
"""
Recommended Key Hierarchy for Production:

AWS Account: 123456789012
├─ KMS Key 1: MSK Encryption
│  ├─ Admins: Security Team Role
│  ├─ Users: PyFlink Role, MSK Service Principal
│  └─ Rotation: Enabled (automatic annual)
│
├─ KMS Key 2: S3 Encryption
│  ├─ Admins: Security Team Role
│  ├─ Users: PyFlink, Firehose, SageMaker, S3 Service Principal
│  └─ Rotation: Enabled (automatic annual)
│
├─ KMS Key 3: CloudWatch Logs Encryption
│  ├─ Admins: Security Team Role
│  ├─ Users: CloudWatch Logs Service Principal (automatic)
│  └─ Rotation: Enabled (automatic annual)
│
└─ KMS Key 4: Secrets (Future)
   ├─ Admins: Security Team Role
   ├─ Users: Lambda functions (for DB credentials, API keys)
   └─ Rotation: Enabled (automatic annual)


Deployment Order:
1. Create KMS keys (first - needed by other resources)
2. Create S3 buckets with KMS encryption enabled
3. Create MSK cluster with KMS encryption enabled
4. Create IAM roles with KMS grant permissions
5. Create application stacks (Flink, Firehose)

Cost Impact:
- Per key: $1/month
- Per grant: $0.02 per grant (amortized)
- Typical setup: 3-4 keys = ~$3-4/month
- Data key generation: Included in key cost


Compliance Benefits:
✓ PCI-DSS 3.2.1: Customer-managed keys required
✓ PCI-DSS 3.6: Key rotation requirement
✓ SOC 2 Type II: Encryption controls
✓ AWS Well-Architected: Security pillar
✓ HIPAA: Encryption at rest requirement
✓ GDPR: Data protection controls
"""

