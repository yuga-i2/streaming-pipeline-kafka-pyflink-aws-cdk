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
from kafka.admin import KafkaAdminClient, NewTopic
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
from kafka.sasl.oauth import AbstractTokenProvider

msk = boto3.client("kafka")

cluster_arn = os.getenv('MSK_CLUSTER_ARN', "arn:aws:kafka:eu-west-1:205336919675:cluster/ServerlessKafkaCluster/af8c98df-1749-49fc-913f-5470844204b7-s1")
input_topic = os.getenv('INPUT_TOPIC_NAME', "input_topic")
output_topic = os.getenv('OUTPUT_TOPIC_NAME', "output_topic")
region = os.getenv('AWS_REGION', "eu-west-1")


def get_brokers(cluster_arn):
    response = msk.get_bootstrap_brokers(ClusterArn=cluster_arn)
    return response["BootstrapBrokerStringSaslIam"]

class MSKTokenProvider(AbstractTokenProvider):
    def token(self):
        token, _ = MSKAuthTokenProvider.generate_auth_token(region)
        return token

def create_topics(brokers, token_provider, topics):
    admin_client = KafkaAdminClient(
        bootstrap_servers=brokers,
        security_protocol='SASL_SSL',
        sasl_mechanism='OAUTHBEARER',
        sasl_oauth_token_provider=token_provider,
        request_timeout_ms=20000,
        api_version_auto_timeout_ms=30000
    )

    topic_list = [NewTopic(name=t, num_partitions=1, replication_factor=1) for t in topics]
    
    try:
        admin_client.create_topics(new_topics=topic_list, validate_only=False)
    except Exception as e:
        if "TopicExistsError" not in str(e):
            raise e  # Ignore if already exists, raise if other error
    finally:
        admin_client.close()

def handler(event, context):
    brokers = get_brokers(cluster_arn)
    tp = MSKTokenProvider()

    # Create topics if not exist
    create_topics(brokers, tp, [input_topic, output_topic])

    # Return the broker string in the custom resource response
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"We have successfully created two topics: {input_topic} and {output_topic} in MSK cluster",
        }),
        "Data": {
            "BootstrapBrokers": brokers
        }
    }

if __name__ == "__main__":
    handler(None, None)
