## Copyright 2025 Amazon.com, Inc. or its affiliates. All Rights Reserved.
## SPDX-License-Identifier: LicenseRef-.amazon.com.-AmznSL-1.0
## Licensed under the Amazon Software License  https://aws.amazon.com/asl/

from aws_cdk import Arn as arn
from aws_cdk import ArnFormat as af
from aws_cdk import Fn as fn

## Helper function
# This function constructs the ARN for a Kafka topic given the ARN of the Kafka cluster and the topic name.
def get_topic_name(kafka_cluster_arn, topic_name):
    _arn = arn.split(kafka_cluster_arn, af.SLASH_RESOURCE_SLASH_RESOURCE_NAME)
    cluster_name = _arn.resource
    cluster_uuid = _arn.resource_name
    prefix_arn = arn.split(kafka_cluster_arn, af.COLON_RESOURCE_NAME)
    arn_with_topic = fn.join(
        delimiter="",
        list_of_values=[
            "arn",
            ":",
            prefix_arn.partition,
            ":",
            prefix_arn.service,
            ":",
            prefix_arn.region,
            ":",
            prefix_arn.account,
            ":topic/",
            cluster_name,
            "/",
            cluster_uuid,
            "/",
            topic_name,
        ],  # type: ignore
    )
    return arn_with_topic

# This function constructs the ARN for a Kafka consumer group given the ARN of the Kafka cluster and the group name.
def get_group_name(kafka_cluster_arn, group_name):
    _arn = arn.split(kafka_cluster_arn, af.SLASH_RESOURCE_SLASH_RESOURCE_NAME)
    cluster_name = _arn.resource
    cluster_uuid = _arn.resource_name
    prefix_arn = arn.split(kafka_cluster_arn, af.COLON_RESOURCE_NAME)
    arn_with_group = fn.join(
        delimiter="",
        list_of_values=[
            "arn",
            ":",
            prefix_arn.partition,
            ":",
            prefix_arn.service,
            ":",
            prefix_arn.region,
            ":",
            prefix_arn.account,
            ":group/",
            cluster_name,
            "/",
            cluster_uuid,
            "/",
            group_name,
        ],  # type: ignore
    )
    return arn_with_group
