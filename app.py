#!/usr/bin/env python3
"""
E-Commerce Order Processing Pipeline - CDK Main Application
============================================================

This application deploys a production-grade real-time order processing pipeline
using Amazon MSK (Kafka), Amazon Managed Flink, and Amazon S3.

Architecture:
1. Event Streaming Stack: MSK Serverless cluster with Kafka topics for order events
2. Order Processing Stack: Flink job for real-time aggregation and enrichment
3. Data Lake Stack: Firehose delivery to S3 for analytics and historical data
4. ML Features Stack: SageMaker Feature Store for real-time ML model serving

Environment Configuration:
- Use CDK_ENV environment variable to select environment (dev, staging, prod)
- Configurations are loaded from config/{environment}.json
- Default environment is 'dev'
"""

import json
import os
import cdk_nag
from aws_cdk import Aspects
import aws_cdk as cdk

from stacks.event_streaming_stack import EventStreamingStack
from stacks.order_processing_stack import OrderProcessingStack
from stacks.data_lake_stack import DataLakeStack
from stacks.ml_features_stack import MLFeaturesStack


def load_config():
    """
    Load configuration from project_config.json and environment-specific config.
    
    Returns:
        dict: Merged configuration dictionary
    """
    # Load base configuration
    with open("project_config.json", "r") as f:
        base_config = json.load(f)
    
    # Load environment-specific config
    environment = os.environ.get("CDK_ENV", base_config.get("project", {}).get("environment", "dev"))
    config_path = f"config/{environment}.json"
    
    try:
        with open(config_path, "r") as f:
            env_config = json.load(f)
        # Merge environment config with base config
        return {**base_config, **env_config}
    except FileNotFoundError:
        print(f"⚠️  Environment config not found: {config_path}. Using base configuration.")
        return base_config


def main():
    """Initialize and synthesize the CDK application."""
    
    config = load_config()
    environment = config.get("environment", "dev")
    
    print(f"🚀 Deploying E-Commerce Order Processing Pipeline")
    print(f"   Environment: {environment}")
    print(f"   Project: {config['project']['name']}")
    
    app = cdk.App()

    # Configure AWS environment
    env = cdk.Environment(
        account=app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION"),
    )

    # Stack 1: Event Streaming Infrastructure (MSK, Kafka topics, Lambda producer)
    event_streaming_stack = EventStreamingStack(
        app,
        config["stacks"]["event_streaming_stack_name"],
        config=config,
        env=env,
        description="E-Commerce event streaming infrastructure with MSK Serverless cluster"
    )

    # Stack 2: Data Lake (Kinesis Firehose → S3)
    data_lake_stack = DataLakeStack(
        app,
        config["stacks"]["data_lake_stack_name"],
        config=config,
        event_streaming_stack=event_streaming_stack,
        env=env,
        description="Data lake for order events using S3 with Firehose delivery"
    )
    data_lake_stack.add_dependency(event_streaming_stack)

    # Stack 3: ML Features (SageMaker Feature Store)
    ml_features_stack = MLFeaturesStack(
        app,
        config["stacks"]["ml_features_stack_name"],
        config=config,
        event_streaming_stack=event_streaming_stack,
        env=env,
        description="Real-time ML features using SageMaker Feature Store"
    )
    ml_features_stack.add_dependency(event_streaming_stack)

    # Stack 4: Stream Processing (Flink)
    order_processing_stack = OrderProcessingStack(
        app,
        config["stacks"]["order_processing_stack_name"],
        config=config,
        event_streaming_stack=event_streaming_stack,
        env=env,
        description="Flink job for real-time order enrichment and aggregation"
    )
    order_processing_stack.add_dependency(event_streaming_stack)

    # Add AWS Solutions Checks for best practices
    Aspects.of(app).add(cdk_nag.AwsSolutionsChecks(reports=True, verbose=True))

    # Synthesize CloudFormation template
    app.synth()


if __name__ == "__main__":
    main()
