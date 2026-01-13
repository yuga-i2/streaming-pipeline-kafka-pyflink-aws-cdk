## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

import os
import json
import boto3
import base64
import datetime

def handler(event, context):
    print("Lambda function started")
    print(f"Event: {event}")

    bucket_name = os.getenv("BUCKET_NAME", "")
    s3 = boto3.client('s3')
    messages = []

    for partition, partition_messages in event['records'].items():
        for message in partition_messages:
            encoded_message = message['value']
            decoded_message = base64.b64decode(encoded_message).decode('utf-8')
            print(f"Decoded message: {decoded_message}")
            
            # Add additional metadata if needed
            message_data = {
                'message': decoded_message,
                'topic': message['topic'],
                'partition': message['partition'],
                'offset': message['offset'],
                'timestamp': message['timestamp']
            }
            messages.append(message_data)

    if messages:
        # Generate a unique filename using the current timestamp
        timestamp = datetime.datetime.now().isoformat()
        filename = f'messages/{timestamp}.json'

        # Write messages to S3
        s3.put_object(
            Bucket=bucket_name,
            Key=filename,
            Body=json.dumps(messages),
            ContentType='application/json'
        )
        print(f"Wrote {len(messages)} messages to S3: s3://{bucket_name}/{filename}")
    else:
        print("No messages to write to S3")

    return {
        'statusCode': 200,
        'body': json.dumps(f'Processed {len(messages)} messages')
    }

if __name__ == "__main__":
    # Get cluster info
    handler(None, None)
