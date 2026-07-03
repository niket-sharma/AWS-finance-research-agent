"""DynamoDB-backed cache keyed by (tool, ticker, date).

Idempotent: same key always returns the same result within TTL.
Degrades gracefully — a DynamoDB failure is logged and the caller
gets None (cache miss); the tool re-fetches from the source.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .model_config import AWS_REGION, CACHE_TABLE, CACHE_TTL_SECS

logger = logging.getLogger(__name__)

_dynamodb = None


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    return _dynamodb.Table(CACHE_TABLE)


def _cache_key(tool: str, ticker: str, date: str) -> str:
    return f"{tool}#{ticker.upper()}#{date}"


def get(tool: str, ticker: str, date: str) -> Any | None:
    """Return cached value or None on miss/error."""
    try:
        resp = _table().get_item(Key={"pk": _cache_key(tool, ticker, date)})
        item = resp.get("Item")
        if not item:
            return None
        if item.get("ttl", 0) < int(time.time()):
            return None
        return json.loads(item["payload"])
    except ClientError as exc:
        logger.warning("cache get failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("cache get unexpected error: %s", exc)
        return None


def put(tool: str, ticker: str, date: str, value: Any, ttl_secs: int = CACHE_TTL_SECS) -> None:
    """Write value to cache; silent on error."""
    try:
        _table().put_item(
            Item={
                "pk": _cache_key(tool, ticker, date),
                "payload": json.dumps(value, default=str),
                "ttl": int(time.time()) + ttl_secs,
            }
        )
    except ClientError as exc:
        logger.warning("cache put failed: %s", exc)
    except Exception as exc:
        logger.warning("cache put unexpected error: %s", exc)
