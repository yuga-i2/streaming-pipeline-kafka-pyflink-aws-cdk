"""
CloudWatch Dashboard templates for PyFlink streaming pipeline.

Provides 4 pre-configured dashboards:
1. "Is the Pipeline Working?" - Health overview
2. "Where's the Bottleneck?" - Performance investigation
3. "What's Broken?" - Error analysis
4. "Can We Handle More?" - Capacity planning
"""

import json
from typing import List, Dict, Any


class DashboardMetricWidget:
    """Single metric widget in CloudWatch dashboard."""
    
    def __init__(self, metric_name: str, stat: str = "Average", 
                 period: int = 60, label: str = None, 
                 yaxis_left_min: int = 0, yaxis_left_max: int = None,
                 color: str = None, dimensions: Dict = None):
        """
        Args:
            metric_name: CloudWatch metric name
            stat: Statistic (Average, Sum, Maximum, Minimum)
            period: Period in seconds
            label: Display label
            yaxis_left_min/max: Y-axis limits
            color: Widget color
            dimensions: Metric dimensions (e.g., {"operator": "deserialization"})
        """
        self.metric_name = metric_name
        self.stat = stat
        self.period = period
        self.label = label or metric_name
        self.yaxis_left_min = yaxis_left_min
        self.yaxis_left_max = yaxis_left_max
        self.color = color
        self.dimensions = dimensions or {}
    
    def to_cloudwatch_metric(self) -> Dict[str, Any]:
        """Convert to CloudWatch metric format."""
        metric_dims = [
            [self.metric_name, {"stat": self.stat}]
        ]
        
        # Add dimensions
        for key, value in self.dimensions.items():
            metric_dims.append([self.metric_name, {key: value, "stat": self.stat}])
        
        return metric_dims


def create_health_dashboard() -> Dict[str, Any]:
    """
    Dashboard 1: "Is the Pipeline Working?"
    
    5 golden signals that indicate if pipeline is healthy:
    1. Kafka Consumer Lag (trending down = keeping up)
    2. DLQ Rate (low = good data quality)
    3. Checkpoint Success (succeeding = state safe)
    4. Processing Latency P99 (SLO met = customers happy)
    5. Window Completeness (>95% = no data loss)
    """
    return {
        "Name": "Ecommerce-StreamingPipeline-Health",
        "Widgets": [
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "consumer_lag_records", 
                         {"stat": "Maximum", "label": "Consumer Lag"}]
                    ],
                    "Period": 60,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "Kafka Consumer Lag (max)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 100000}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 10000, "Label": "Normal", "Color": "#2ca02c"},
                            {"Value": 50000, "Label": "Alert", "Color": "#ff7f0e"},
                        ]
                    }
                },
                "X": 0, "Y": 0, "Width": 6, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "DLQRecordCount", {"stat": "Sum", "label": "DLQ Rate"}]
                    ],
                    "Period": 60,
                    "Stat": "Sum",
                    "Region": "us-east-1",
                    "Title": "DLQ Records/Minute",
                    "Yaxis": {"Left": {"Min": 0, "Max": 500}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 10, "Label": "Normal", "Color": "#2ca02c"},
                            {"Value": 100, "Label": "Critical", "Color": "#d62728"},
                        ]
                    }
                },
                "X": 6, "Y": 0, "Width": 6, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "checkpoint_failures_total", 
                         {"stat": "Sum", "label": "Checkpoint Failures"}]
                    ],
                    "Period": 60,
                    "Stat": "Sum",
                    "Region": "us-east-1",
                    "Title": "Checkpoint Failures (5min)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 10}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 1, "Label": "Alert", "Color": "#d62728"}
                        ]
                    }
                },
                "X": 12, "Y": 0, "Width": 6, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "LatencyP99", 
                         {"stat": "Average", "label": "P99 Latency"}]
                    ],
                    "Period": 60,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "Processing Latency P99 (ms)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 10000}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 2000, "Label": "Target", "Color": "#2ca02c"},
                            {"Value": 5000, "Label": "SLO", "Color": "#ff7f0e"},
                        ]
                    }
                },
                "X": 18, "Y": 0, "Width": 6, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "WindowCompleteness", 
                         {"stat": "Average", "label": "Completeness %"}]
                    ],
                    "Period": 300,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "Window Completeness (%)",
                    "Yaxis": {"Left": {"Min": 90, "Max": 100.5}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 100, "Label": "Perfect", "Color": "#2ca02c"},
                            {"Value": 95, "Label": "Minimum", "Color": "#ff7f0e"},
                        ]
                    }
                },
                "X": 0, "Y": 6, "Width": 12, "Height": 6
            },
            {
                "Type": "log",
                "Properties": {
                    "Query": """
fields @timestamp, @message, order_id, error_type
| filter error_type in ["parse_error", "duplicate", "validation_error"]
| stats count() as errors by error_type
                    """,
                    "Region": "us-east-1",
                    "Title": "Recent Errors (Last Hour)",
                },
                "X": 12, "Y": 6, "Width": 12, "Height": 6
            }
        ]
    }


def create_performance_dashboard() -> Dict[str, Any]:
    """
    Dashboard 2: "Where's the Bottleneck?"
    
    Diagnose performance issues:
    - Throughput in vs. out (stacked bars)
    - Checkpoint duration (trend)
    - Memory usage (% with trend)
    - CPU usage (% with trend)
    - Buffer usage (operator queue depth)
    """
    return {
        "Name": "Ecommerce-StreamingPipeline-Performance",
        "Widgets": [
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "RecordsIn", 
                         {"stat": "Sum", "label": "Records In"}],
                        [".", "RecordsOut", 
                         {"stat": "Sum", "label": "Records Out"}]
                    ],
                    "Period": 60,
                    "Stat": "Sum",
                    "Region": "us-east-1",
                    "Title": "Throughput: In vs. Out (records/min)",
                    "Yaxis": {"Left": {"Min": 0}},
                    "SetPeriodToTimeRange": True,
                },
                "X": 0, "Y": 0, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "checkpoint_duration_ms", 
                         {"stat": "Average", "label": "Avg"}],
                        [".", "checkpoint_duration_ms", 
                         {"stat": "Maximum", "label": "Max"}]
                    ],
                    "Period": 60,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "Checkpoint Duration (ms)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 60000}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 10000, "Label": "Normal", "Color": "#2ca02c"},
                            {"Value": 30000, "Label": "Slow", "Color": "#ff7f0e"},
                        ]
                    }
                },
                "X": 12, "Y": 0, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "memory_usage_percentage", 
                         {"stat": "Average", "label": "Avg Memory %"}],
                        [".", "memory_usage_percentage", 
                         {"stat": "Maximum", "label": "Max Memory %"}]
                    ],
                    "Period": 60,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "Heap Memory Usage (%)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 100}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 70, "Label": "Safe", "Color": "#2ca02c"},
                            {"Value": 85, "Label": "Alert", "Color": "#ff7f0e"},
                            {"Value": 95, "Label": "OOM Risk", "Color": "#d62728"},
                        ]
                    }
                },
                "X": 0, "Y": 6, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "cpu_usage_percentage", 
                         {"stat": "Average", "label": "Avg CPU %"}],
                        [".", "cpu_usage_percentage", 
                         {"stat": "Maximum", "label": "Max CPU %"}]
                    ],
                    "Period": 60,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "CPU Usage (%)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 100}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 70, "Label": "Good", "Color": "#2ca02c"},
                            {"Value": 90, "Label": "Saturated", "Color": "#ff7f0e"},
                        ]
                    }
                },
                "X": 12, "Y": 6, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "LatencyP50", {"stat": "Average"}],
                        [".", "LatencyP95", {"stat": "Average"}],
                        [".", "LatencyP99", {"stat": "Average"}]
                    ],
                    "Period": 60,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "Latency Percentiles (ms)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 10000}},
                },
                "X": 0, "Y": 12, "Width": 12, "Height": 6
            },
            {
                "Type": "log",
                "Properties": {
                    "Query": """
fields operator, @duration
| stats avg(@duration) as avg_latency, max(@duration) as max_latency 
  by operator
| sort avg_latency desc
                    """,
                    "Region": "us-east-1",
                    "Title": "Latency by Operator (ms)",
                },
                "X": 12, "Y": 12, "Width": 12, "Height": 6
            }
        ]
    }


def create_errors_dashboard() -> Dict[str, Any]:
    """
    Dashboard 3: "What's Broken?"
    
    Diagnose errors:
    - DLQ breakdown by error type (pie chart)
    - Error rate by operator
    - Firehose delivery status
    - Deserialization errors
    """
    return {
        "Name": "Ecommerce-StreamingPipeline-Errors",
        "Widgets": [
            {
                "Type": "log",
                "Properties": {
                    "Query": """
fields error_type
| filter error_type in ["parse_error", "duplicate", "validation_error", "timeout"]
| stats count() as count by error_type
| sort count desc
                    """,
                    "Region": "us-east-1",
                    "Title": "DLQ Records by Error Type (Last Hour)",
                },
                "X": 0, "Y": 0, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "DLQRecordByType", 
                         {"error_type": "parse_error", "stat": "Sum"}],
                        [".", "DLQRecordByType", 
                         {"error_type": "duplicate", "stat": "Sum"}],
                        [".", "DLQRecordByType", 
                         {"error_type": "validation_failed", "stat": "Sum"}]
                    ],
                    "Period": 60,
                    "Stat": "Sum",
                    "Region": "us-east-1",
                    "Title": "DLQ Breakdown by Type",
                    "Yaxis": {"Left": {"Min": 0}},
                },
                "X": 12, "Y": 0, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "firehose_failed_put_count", 
                         {"stat": "Sum", "label": "Firehose Failures"}],
                        [".", "kafka_deserialization_errors_total", 
                         {"stat": "Sum", "label": "Deser Errors"}]
                    ],
                    "Period": 60,
                    "Stat": "Sum",
                    "Region": "us-east-1",
                    "Title": "Critical Errors (failures, deser errors)",
                    "Yaxis": {"Left": {"Min": 0}},
                },
                "X": 0, "Y": 6, "Width": 12, "Height": 6
            },
            {
                "Type": "log",
                "Properties": {
                    "Query": """
fields @timestamp, order_id, @message, error_type
| filter error_type != ""
| stats count() as error_count by order_id
| sort error_count desc
| limit 20
                    """,
                    "Region": "us-east-1",
                    "Title": "Top 20 Orders with Most Errors",
                },
                "X": 12, "Y": 6, "Width": 12, "Height": 6
            },
            {
                "Type": "log",
                "Properties": {
                    "Query": """
fields @timestamp, @message
| filter error_type = "timeout"
| stats count() as timeout_count by bin(5m)
                    """,
                    "Region": "us-east-1",
                    "Title": "Timeout Trend (5min buckets)",
                },
                "X": 0, "Y": 12, "Width": 12, "Height": 6
            },
            {
                "Type": "log",
                "Properties": {
                    "Query": """
fields @timestamp, @message, operator
| filter level = "ERROR"
| stats count() as error_count by operator
| sort error_count desc
                    """,
                    "Region": "us-east-1",
                    "Title": "Errors by Operator",
                },
                "X": 12, "Y": 12, "Width": 12, "Height": 6
            }
        ]
    }


def create_capacity_dashboard() -> Dict[str, Any]:
    """
    Dashboard 4: "Can We Handle More?"
    
    Capacity planning:
    - CPU, Memory, Network utilization
    - Kafka brokers alive
    - Flink task managers alive
    - State backend storage used
    - Firehose throttles
    """
    return {
        "Name": "Ecommerce-StreamingPipeline-Capacity",
        "Widgets": [
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "cpu_usage_percentage", 
                         {"stat": "Average", "label": "CPU Avg"}],
                        [".", "memory_usage_percentage", 
                         {"stat": "Average", "label": "Memory Avg"}]
                    ],
                    "Period": 300,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "CPU & Memory Utilization (5min avg)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 100}},
                },
                "X": 0, "Y": 0, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "kafka_broker_alive_count", 
                         {"stat": "Minimum", "label": "Brokers Alive"}]
                    ],
                    "Period": 60,
                    "Stat": "Minimum",
                    "Region": "us-east-1",
                    "Title": "Kafka Broker Count (min = degradation indicator)",
                    "Yaxis": {"Left": {"Min": 0, "Max": 4}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 3, "Label": "Normal", "Color": "#2ca02c"},
                            {"Value": 2, "Label": "Degraded", "Color": "#ff7f0e"},
                            {"Value": 1, "Label": "Critical", "Color": "#d62728"},
                        ]
                    }
                },
                "X": 12, "Y": 0, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "task_manager_count", 
                         {"stat": "Minimum", "label": "Task Managers"}]
                    ],
                    "Period": 60,
                    "Stat": "Minimum",
                    "Region": "us-east-1",
                    "Title": "Flink Task Managers (minimum)",
                    "Yaxis": {"Left": {"Min": 0}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 2, "Label": "Minimum Required", "Color": "#ff7f0e"}
                        ]
                    }
                },
                "X": 0, "Y": 6, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "state_backend_used_bytes", 
                         {"stat": "Average", "label": "State Size (bytes)"}]
                    ],
                    "Period": 300,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "State Backend Size (bytes)",
                    "Yaxis": {"Left": {"Min": 0}},
                },
                "X": 12, "Y": 6, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "firehose_throttle_count", 
                         {"stat": "Sum", "label": "Throttles"}]
                    ],
                    "Period": 60,
                    "Stat": "Sum",
                    "Region": "us-east-1",
                    "Title": "Firehose Throttles (requests rejected)",
                    "Yaxis": {"Left": {"Min": 0}},
                    "Annotations": {
                        "Horizontal": [
                            {"Value": 1, "Label": "Any throttle = issue", "Color": "#ff7f0e"}
                        ]
                    }
                },
                "X": 0, "Y": 12, "Width": 12, "Height": 6
            },
            {
                "Type": "metric",
                "Properties": {
                    "Metrics": [
                        ["ecommerce-streaming", "network_in_bytes_per_second", 
                         {"stat": "Average", "label": "In"}],
                        [".", "network_out_bytes_per_second", 
                         {"stat": "Average", "label": "Out"}]
                    ],
                    "Period": 300,
                    "Stat": "Average",
                    "Region": "us-east-1",
                    "Title": "Network Throughput (bytes/sec, 5min avg)",
                    "Yaxis": {"Left": {"Min": 0}},
                },
                "X": 12, "Y": 12, "Width": 12, "Height": 6
            }
        ]
    }


def export_dashboards_as_json(output_file: str = "dashboards.json"):
    """Export all 4 dashboards as JSON."""
    dashboards = [
        create_health_dashboard(),
        create_performance_dashboard(),
        create_errors_dashboard(),
        create_capacity_dashboard(),
    ]
    
    with open(output_file, "w") as f:
        json.dump(dashboards, f, indent=2)
    
    print(f"Exported {len(dashboards)} dashboards to {output_file}")


# ============================================================================
# CloudWatch Dashboard Creation Instructions
# ============================================================================

DASHBOARD_SETUP_INSTRUCTIONS = """
CLOUDWATCH DASHBOARD SETUP

Option 1: Using AWS CLI
======================
# Export dashboards to JSON
python3 cloudwatch_dashboards.py

# Create each dashboard
aws cloudwatch put-dashboard \\
  --dashboard-name "Ecommerce-StreamingPipeline-Health" \\
  --dashboard-body file://health-dashboard.json

Option 2: Using AWS Console
===========================
1. Go to CloudWatch > Dashboards
2. Create new dashboard
3. Paste JSON from export
4. Save

Option 3: Using CDK (Recommended)
=================================
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk.core import Stack, Construct

class MonitoringStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs):
        super().__init__(scope, id, **kwargs)
        
        # Create 4 dashboards from JSON
        dashboards = export_dashboards_as_json()
        
        for dashboard_config in dashboards:
            cloudwatch.Dashboard(
                self, 
                dashboard_config["Name"],
                dashboard_name=dashboard_config["Name"]
            )

DASHBOARD USAGE
===============
1. Open "Ecommerce-StreamingPipeline-Health" first (overall status)
2. If health is bad, switch to "Performance" (find bottleneck)
3. If errors increasing, switch to "Errors" (diagnose issue)
4. For capacity planning, check "Capacity" dashboard

INTERPRETATION GUIDE
====================
Green zone  = Normal operation (no action needed)
Yellow zone = Monitor, investigate if trend continues
Red zone    = Alert triggered, page on-call

Example: Consumer Lag
- Green: <10K records (normal)
- Yellow: 10-50K records (investigate throughput)
- Red: >50K records (escalate)

REFRESH RATES
=============
All dashboards refresh every 60 seconds (1 minute).
For real-time monitoring, use CloudWatch Logs Insights instead.

CUSTOM QUERIES
==============
Use CloudWatch Logs Insights for ad-hoc analysis:
- Trace order through pipeline
- Find slow requests
- Analyze errors by operator
- Calculate percentiles
"""


if __name__ == "__main__":
    export_dashboards_as_json()
    print("\n" + DASHBOARD_SETUP_INSTRUCTIONS)
