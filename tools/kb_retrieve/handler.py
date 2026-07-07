"""Bedrock Knowledge Base retrieval tool — grounds fundamentals narrative in filing text.

Wraps the Bedrock Agent Runtime `retrieve` API against the S3-Vectors-backed
Knowledge Base built in Phase 1. Degrades gracefully to status="unavailable"
if no KB is configured (e.g. running locally before deploy) or the call fails.

Lambda entry point: lambda_handler(event, context).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

AWS_REGION = os.environ.get("AWS_REGION_NAME", "us-east-1")

_bedrock_agent_runtime = None


def _client():
    global _bedrock_agent_runtime
    if _bedrock_agent_runtime is None:
        _bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
    return _bedrock_agent_runtime


def retrieve_passages(query: str, ticker: str | None = None, max_results: int = 5) -> dict[str, Any]:
    """Retrieve grounding passages from the filings Knowledge Base.

    Args:
        query: Natural-language query (e.g. "AAPL revenue growth drivers").
        ticker: Optional ticker to bias the query text.
        max_results: Max passages to return.

    Returns:
        dict with keys: query, passages (list of {text, source, score}), status.
    """
    kb_id = os.environ.get("KB_ID")
    if not kb_id:
        return {"query": query, "passages": [], "status": "unavailable", "reason": "KB_ID not configured"}

    full_query = f"{ticker}: {query}" if ticker else query

    try:
        resp = _client().retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": full_query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": max_results},
            },
        )
    except ClientError as exc:
        logger.warning("kb_retrieve failed: %s", exc)
        return {"query": query, "passages": [], "status": "unavailable", "reason": str(exc)}

    passages = []
    for result in resp.get("retrievalResults", []):
        content = result.get("content", {}).get("text", "")
        location = result.get("location", {})
        source_uri = (
            location.get("s3Location", {}).get("uri")
            or location.get("webLocation", {}).get("url")
            or ""
        )
        passages.append({
            "text": content,
            "source": source_uri,
            "score": result.get("score", 0.0),
        })

    return {"query": query, "passages": passages, "status": "ok"}


def lambda_handler(event: dict, context: Any) -> dict:
    try:
        body = event if isinstance(event, dict) else json.loads(event)
        result = retrieve_passages(
            query=body["query"],
            ticker=body.get("ticker"),
            max_results=body.get("max_results", 5),
        )
        return {"statusCode": 200, "body": json.dumps(result)}
    except KeyError as exc:
        logger.error("kb_retrieve error: %s", exc)
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.error("kb_retrieve unexpected error: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
