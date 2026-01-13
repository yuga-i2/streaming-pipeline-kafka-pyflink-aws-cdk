## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import (
    RemovalPolicy,
    aws_s3 as s3,
)

class S3Factory:
    """
    Factory class for creating and configuring S3 buckets.
    """
    
    @staticmethod
    def create_secure_bucket(
        scope,
        id,
        bucket_name=None,
        removal_policy=RemovalPolicy.DESTROY,
        auto_delete_objects=True,
        access_logs_bucket=None,
        versioned=False,
    ):
        """
        Creates a secure S3 bucket with best practices.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the bucket
            removal_policy: The removal policy for the bucket
            auto_delete_objects: Whether to automatically delete objects when the bucket is deleted
            access_logs_bucket: The bucket to store access logs in
            versioned: Whether to enable versioning on the bucket
            
        Returns:
            The created bucket
        """
        bucket_props = {
            "removal_policy": removal_policy,
            "block_public_access": s3.BlockPublicAccess.BLOCK_ALL,
            "encryption": s3.BucketEncryption.S3_MANAGED,
            "enforce_ssl": True,
            "auto_delete_objects": auto_delete_objects,
            "versioned": versioned,
        }
        
        if access_logs_bucket:
            bucket_props["server_access_logs_bucket"] = access_logs_bucket
        if bucket_name:
            bucket_props["bucket_name"] = bucket_name
        
        return s3.Bucket(scope, id, **bucket_props)
    
    @staticmethod
    def create_access_logs_bucket(scope, id):
        """
        Creates an S3 bucket specifically for access logs.
        
        Args:
            scope: The CDK construct scope
            id: The ID for the bucket
            
        Returns:
            The created access logs bucket
        """
        return s3.Bucket(
            scope,
            id,
            removal_policy=RemovalPolicy.DESTROY,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            auto_delete_objects=True,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
        )
