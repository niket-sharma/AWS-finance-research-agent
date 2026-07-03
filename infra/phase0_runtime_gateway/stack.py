"""CDK stack — Phase 0: DynamoDB cache + 6 tool Lambdas + AgentCore Gateway.

Every resource is tagged: Project=research-desk, Phase=0, Env=learning.
"""

from __future__ import annotations

import os

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from constructs import Construct

COMMON_TAGS = {"Project": "research-desk", "Phase": "0", "Env": "learning"}
REGION = "us-east-1"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# Exclude non-source artifacts from Lambda packaging
LAMBDA_EXCLUDES = [
    ".venv",
    "cdk.out",
    ".git",
    "layer",
    "infra",
    "knowledge",
    "eval",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    "node_modules",
    "*.md",
    "Makefile",
    "ruff.toml",
    "pytest.ini",
    "conftest.py",
    "requirements*.txt",
]

TOOL_CONFIGS = [
    {"name": "edgar-filings",        "handler": "tools.edgar_filings.handler.lambda_handler"},
    {"name": "edgar-company-facts",  "handler": "tools.edgar_company_facts.handler.lambda_handler"},
    {"name": "market-data",          "handler": "tools.market_data.handler.lambda_handler"},
    {"name": "risk-metrics",         "handler": "tools.risk_metrics.handler.lambda_handler"},
    {"name": "regime-classifier",    "handler": "tools.regime_classifier.handler.lambda_handler"},
    {"name": "news-search",          "handler": "tools.news_search.handler.lambda_handler"},
]


def _apply_tags(construct: Construct) -> None:
    for k, v in COMMON_TAGS.items():
        Tags.of(construct).add(k, v)


class Phase0Stack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        _apply_tags(self)

        # ── Cache table ──────────────────────────────────────────────────────
        self.cache_table = dynamodb.Table(
            self,
            "CacheTable",
            table_name="research-desk-cache",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        # ── Shared Lambda execution role ─────────────────────────────────────
        lambda_role = iam.Role(
            self,
            "ToolLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        self.cache_table.grant_read_write_data(lambda_role)
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{REGION}:*:secret:research-desk/*",
                ],
            )
        )

        # ── Lambda Layer — dependencies ──────────────────────────────────────
        deps_layer = _lambda.LayerVersion(
            self,
            "DepsLayer",
            code=_lambda.Code.from_asset(os.path.join(REPO_ROOT, "layer")),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="research-desk tool dependencies (boto3, requests, numpy, yfinance, tenacity)",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── Tool Lambdas ─────────────────────────────────────────────────────
        self.tool_lambdas: dict[str, _lambda.Function] = {}
        for cfg in TOOL_CONFIGS:
            fn = _lambda.Function(
                self,
                f"Tool-{cfg['name']}",
                function_name=f"research-desk-{cfg['name']}",
                runtime=_lambda.Runtime.PYTHON_3_12,
                handler=cfg["handler"],
                code=_lambda.Code.from_asset(REPO_ROOT, exclude=LAMBDA_EXCLUDES),
                role=lambda_role,
                layers=[deps_layer],
                timeout=Duration.seconds(60),
                memory_size=512,
                environment={
                    "CACHE_TABLE": "research-desk-cache",
                    "AWS_REGION_NAME": REGION,
                    "LOG_LEVEL": "INFO",
                },
                log_retention=logs.RetentionDays.THREE_DAYS,
            )
            _apply_tags(fn)
            self.tool_lambdas[cfg["name"]] = fn

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "CacheTableName", value=self.cache_table.table_name)
        for name, fn in self.tool_lambdas.items():
            cdk.CfnOutput(self, f"Lambda-{name}", value=fn.function_arn)
