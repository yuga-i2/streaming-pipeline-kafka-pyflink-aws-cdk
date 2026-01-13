## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

import json
import boto3
import time
import datetime
import os
import base64
from botocore.exceptions import ClientError
import uuid

# Initialize SageMaker Feature Store client
sagemaker_client = boto3.client('sagemaker')
featurestore_runtime = boto3.client('sagemaker-featurestore-runtime')

def handler(event, context):
    print("Processing feature store event")
    print(event)
    
    # Get feature group name from environment variable or use default
    feature_group_name = os.environ.get('FEATURE_GROUP_NAME', 'feature-vector-group')
    
    # Process Kafka records
    if isinstance(event, dict) and 'records' in event:
        # Handle Kafka event source
        for topic_partition, records in event['records'].items():
            for record in records:
                try:
                    # Decode base64 value
                    if 'value' in record:
                        payload = base64.b64decode(record['value']).decode('utf-8')
                        # print payload
                        print(f"Decoded payload: {payload}")
                        try:
                            # Parse the record value as JSON
                            data = json.loads(payload)
                            process_consumer_record(data, feature_group_name)
                        except json.JSONDecodeError as e:
                            print(f"Error parsing record value as JSON: {e}")
                            print(f"Raw payload: {payload}")
                except Exception as e:
                    print(f"Error processing Kafka record: {e}")
    elif isinstance(event, list):
        # Handle direct list of records
        for record in event:
            process_consumer_record(record, feature_group_name)
    elif isinstance(event, dict):
        # Handle single record
        process_consumer_record(event, feature_group_name)
    else:
        print(f"Unsupported event format: {type(event)}")
        return {
            'statusCode': 400,
            'body': json.dumps('Unsupported event format')
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps('Data successfully ingested into Feature Store')
    }

def process_consumer_record(record, feature_group_name):
    """
    Process a single stock record and ingest it into the Feature Store.
    
    Args:
        record: Dictionary containing stock data (datetime, ticker, price)
        feature_group_name: Name of the feature group to ingest data into
    """
    try:
        # Generate unique ID for this record
        record_id = str(uuid.uuid4())
        
        # Get event time from record or use current time
        event_time = record.get('datetime', datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"))
        
        # Prepare record for Feature Store
        feature_record = {
            'id': record_id,
            'ticker': str(record.get('ticker', '')),
            'price': str(record.get('price', '0.0')),
            'datetime': str(record.get('datetime', '')),
            'event_time': event_time
        }
        
        # Convert to feature store format (list of dictionaries with feature name and value)
        feature_list = []
        for feature_name, feature_value in feature_record.items():
            feature_list.append({
                'FeatureName': feature_name,
                'ValueAsString': feature_value
            })
        
        print(feature_list)
        # Ingest into Feature Store (will go to both online and offline stores)
        response = featurestore_runtime.put_record(
            FeatureGroupName=feature_group_name,
            Record=feature_list
        )
        
        print(f"Successfully ingested stock record: {record.get('ticker')} at ${record.get('price')} into feature group: {feature_group_name}")
        return response
    
    except ClientError as e:
        print(f"Error ingesting record into Feature Store: {e}")
        raise e
    except Exception as e:
        print(f"Unexpected error processing record: {e}")
        raise e

# For local testing
if __name__ == "__main__":    
    event = None
    handler(event, None)
