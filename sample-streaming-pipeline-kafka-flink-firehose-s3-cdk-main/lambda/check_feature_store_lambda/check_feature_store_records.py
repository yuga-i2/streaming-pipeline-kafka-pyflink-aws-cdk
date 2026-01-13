## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

import boto3

# Hardcoded values
region = "eu-west-1"
feature_group_name = "feature-vector-group"
record_identifiers = ["d80887d5-2da6-49cc-9a28-cbac64c98135", "bef750a9-ccdb-444e-9588-ccb82a436a41"]  # Replace with actual IDs
record_identifier_name = "record_id"        # Replace with your primary key feature name

# Create SageMaker Runtime client
runtime_client = boto3.client("sagemaker-featurestore-runtime", region_name=region)


for record_id in record_identifiers:
    response = runtime_client.get_record(
        FeatureGroupName=feature_group_name,
        RecordIdentifierValueAsString=record_id
    )
    
    print(f"Record for {record_id}:")
    for feature in response['Record']:
        print(feature)
    print("---")
