## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

import boto3
import datetime
import json
import os
import uuid
import random
from kafka import KafkaProducer
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
from kafka.sasl.oauth import AbstractTokenProvider

msk = boto3.client("kafka")

cluster_arn = os.getenv('MSK_CLUSTER_ARN', "")
topic = os.getenv('INPUT_TOPIC_NAME', "input_topic")
region = os.getenv('AWS_REGION', "eu-west-1")


def get_brokers(cluster_arn):
    response = msk.get_bootstrap_brokers(ClusterArn=cluster_arn)
    return response["BootstrapBrokerStringSaslIam"]

class MSKTokenProvider(AbstractTokenProvider):
    def token(self):
        token, _ = MSKAuthTokenProvider.generate_auth_token(region)
        return token
    
def handler(event, context):
    
    brokers = get_brokers(cluster_arn)
    tp = MSKTokenProvider()

    producer = KafkaProducer(bootstrap_servers=brokers,
                                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                                retry_backoff_ms=500,
                                request_timeout_ms=20000,
                                security_protocol='SASL_SSL',
                                sasl_mechanism='OAUTHBEARER',
                                sasl_oauth_token_provider=tp,
                            )
    
    # List of stock tickers
    stock_tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "NFLX", "AMD", "INTC"]

    last_message = None

    for _ in range(2):
        # Generate a random stock message matching the Stock class structure
        message = {
            "datetime": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ticker": random.choice(stock_tickers),  # nosec B311
            "price": round(random.uniform(50.0, 500.0), 2)  # nosec B311
        }

        # Send the message to Kafka
        producer.send(topic, value=message)

        # Store the last message
        last_message = message

    # Flush the producer to ensure all messages are sent
    producer.flush()

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Successfully sent 10 messages to Kafka.",
            "Last message": last_message
        })
    }

if __name__ == "__main__":
    # For local testing
    handler(None, None)
