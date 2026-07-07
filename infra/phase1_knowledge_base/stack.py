"""CDK stack — Phase 1: Bedrock Knowledge Base on S3 Vectors + kb_retrieve Lambda.

Cost guard: S3 Vectors (not OpenSearch Serverless) — verify in console after deploy.
Corpus is tiny (3-5 filings) in knowledge/corpus/, synced to S3 at deploy time.

Every resource is tagged: Project=research-desk, Phase=1, Env=learning.
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
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deployment
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct

COMMON_TAGS = {"Project": "research-desk", "Phase": "1", "Env": "learning"}
REGION = "us-east-1"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSION = 1024

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

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


def _apply_tags(construct: Construct) -> None:
    for k, v in COMMON_TAGS.items():
        Tags.of(construct).add(k, v)


class Phase1Stack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        _apply_tags(self)

        embedding_model_arn = f"arn:aws:bedrock:{REGION}::foundation-model/{EMBEDDING_MODEL_ID}"

        # ── Corpus bucket (source docs for KB ingestion) ───────────────────────
        corpus_bucket = s3.Bucket(
            self,
            "CorpusBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )
        s3_deployment.BucketDeployment(
            self,
            "CorpusDeployment",
            sources=[s3_deployment.Source.asset(os.path.join(REPO_ROOT, "knowledge/corpus"))],
            destination_bucket=corpus_bucket,
        )

        # ── S3 Vectors store (cost guard: not OpenSearch) ───────────────────────
        vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "VectorBucket",
            vector_bucket_name="research-desk-kb-vectors",
        )
        vector_index = s3vectors.CfnIndex(
            self,
            "VectorIndex",
            index_name="research-desk-kb-index",
            vector_bucket_name=vector_bucket.vector_bucket_name,
            data_type="float32",
            dimension=EMBEDDING_DIMENSION,
            distance_metric="cosine",
            # Bedrock stores each chunk's source text as filterable metadata by default,
            # capped at 2048 bytes total — our 500-token chunks routinely exceed that.
            # Marking these keys non-filterable raises the cap to 40KB/vector.
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"],
            ),
        )
        vector_index.add_dependency(vector_bucket)

        # ── Knowledge Base service role ──────────────────────────────────────
        kb_role = iam.Role(
            self,
            "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            ),
        )
        corpus_bucket.grant_read(kb_role)
        # Explicit iam.Policy (not role.add_to_policy) so we get a construct handle to
        # depend on — CfnKnowledgeBase only references role_arn, which does NOT imply a
        # dependency on this policy's attachment. Without it, CloudFormation creates the
        # policy and the KB in parallel, and Bedrock validates s3vectors permissions
        # before IAM has propagated them (403 on s3vectors:QueryVectors, seen in practice).
        kb_permissions = iam.Policy(
            self,
            "KnowledgeBasePermissions",
            statements=[
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel"],
                    resources=[embedding_model_arn],
                ),
                iam.PolicyStatement(
                    actions=["s3vectors:*"],
                    resources=[
                        vector_bucket.attr_vector_bucket_arn,
                        vector_index.attr_index_arn,
                    ],
                ),
            ],
        )
        kb_permissions.attach_to_role(kb_role)

        # ── Knowledge Base ───────────────────────────────────────────────────
        knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "FilingsKnowledgeBase",
            name="research-desk-filings-kb",
            description="Grounding corpus of 10-K/10-Q filing text for fundamentals narrative.",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=embedding_model_arn,
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
                    index_arn=vector_index.attr_index_arn,
                ),
            ),
        )
        knowledge_base.add_dependency(vector_index)
        knowledge_base.node.add_dependency(kb_permissions)
        _apply_tags(knowledge_base)

        # ── Data source (corpus bucket → KB) ────────────────────────────────
        data_source = bedrock.CfnDataSource(
            self,
            "FilingsDataSource",
            name="research-desk-filings-source",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=corpus_bucket.bucket_arn,
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=500,
                        overlap_percentage=20,
                    ),
                ),
            ),
        )

        # ── kb_retrieve Lambda ───────────────────────────────────────────────
        lambda_role = iam.Role(
            self,
            "KbRetrieveLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
        )
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:Retrieve"],
                resources=[knowledge_base.attr_knowledge_base_arn],
            )
        )

        deps_layer = _lambda.LayerVersion(
            self,
            "KbDepsLayer",
            code=_lambda.Code.from_asset(os.path.join(REPO_ROOT, "layer")),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="research-desk kb_retrieve dependencies (boto3)",
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.kb_retrieve_lambda = _lambda.Function(
            self,
            "Tool-kb-retrieve",
            function_name="research-desk-kb-retrieve",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="tools.kb_retrieve.handler.lambda_handler",
            code=_lambda.Code.from_asset(REPO_ROOT, exclude=LAMBDA_EXCLUDES),
            role=lambda_role,
            layers=[deps_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "KB_ID": knowledge_base.attr_knowledge_base_id,
                "AWS_REGION_NAME": REGION,
                "LOG_LEVEL": "INFO",
            },
            log_retention=logs.RetentionDays.THREE_DAYS,
        )
        _apply_tags(self.kb_retrieve_lambda)

        # ── Outputs ──────────────────────────────────────────────────────────
        cdk.CfnOutput(self, "KnowledgeBaseId", value=knowledge_base.attr_knowledge_base_id)
        cdk.CfnOutput(self, "DataSourceId", value=data_source.attr_data_source_id)
        cdk.CfnOutput(self, "CorpusBucketName", value=corpus_bucket.bucket_name)
        cdk.CfnOutput(self, "LambdaKbRetrieve", value=self.kb_retrieve_lambda.function_arn)
