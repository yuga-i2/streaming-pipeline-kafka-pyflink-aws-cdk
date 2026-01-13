"""
PyFlink Order Processing Application

A production-grade real-time order processing pipeline using PyFlink (Python API for Apache Flink).

Modules:
    - models: Data schemas (OrderEvent, EnrichedOrder, OrderValidationError, OrderAggregation)
    - order_processor: Main Flink job with validation, enrichment, deduplication, windowing

Usage:
    python -m flink_pyflink_app.order_processor
"""

__version__ = "1.0.0"
__author__ = "Data Engineering Team"
