"""News search tool — fetches recent headlines for a ticker.

Uses Finnhub free tier (key in Secrets Manager) by default.
Degrades gracefully: if the key is absent or the provider fails, returns
status="unavailable" with a neutral sentiment — the ResearchNote still renders.

Lambda entry point: lambda_handler(event, context).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

import boto3
import requests
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from shared.cache import get as cache_get
    from shared.cache import put as cache_put
    from shared.model_config import AWS_REGION
except ImportError:
    def cache_get(*_a, **_kw):
        return None
    def cache_put(*_a, **_kw):
        pass
    AWS_REGION = "us-east-1"

logger = logging.getLogger(__name__)

SECRET_NAME = "research-desk/news-api-key"
_api_key_cache: str | None = None


def _get_api_key() -> str | None:
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    try:
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        resp = sm.get_secret_value(SecretId=SECRET_NAME)
        secret = json.loads(resp["SecretString"])
        _api_key_cache = secret.get("api_key")
        return _api_key_cache
    except ClientError as exc:
        logger.warning("Could not load news API key: %s", exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected error loading news API key: %s", exc)
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _finnhub_news(ticker: str, api_key: str, days: int = 7) -> list[dict]:
    end = date.today()
    start = end - timedelta(days=days)
    url = "https://finnhub.io/api/v1/company-news"
    resp = requests.get(
        url,
        params={"symbol": ticker, "from": start.isoformat(), "to": end.isoformat(), "token": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def search_news(ticker: str, limit: int = 10) -> dict[str, Any]:
    """Return recent news headlines for ticker with metadata.

    Args:
        ticker: Equity ticker (e.g. "AAPL").
        limit: Max headlines to return.

    Returns:
        dict with headlines, sources, status ("ok" or "unavailable").
    """
    today = date.today().isoformat()
    cached = cache_get("news_search", ticker, today)
    if cached is not None:
        return cached

    api_key = _get_api_key()
    if not api_key:
        result = {
            "ticker": ticker.upper(),
            "headlines": [],
            "sources": [],
            "status": "unavailable",
            "reason": "API key not configured",
        }
        return result

    try:
        articles = _finnhub_news(ticker, api_key)
        headlines = [a.get("headline", "") for a in articles if a.get("headline")][:limit]
        sources = list({a.get("source", "") for a in articles if a.get("source")})
        result = {
            "ticker": ticker.upper(),
            "headlines": headlines,
            "sources": sources,
            "status": "ok",
        }
        cache_put("news_search", ticker, today, result)
        return result
    except Exception as exc:
        logger.warning("news_search failed for %s: %s", ticker, exc)
        return {
            "ticker": ticker.upper(),
            "headlines": [],
            "sources": [],
            "status": "unavailable",
            "reason": str(exc),
        }


def lambda_handler(event: dict, context: Any) -> dict:
    try:
        body = event if isinstance(event, dict) else json.loads(event)
        result = search_news(ticker=body["ticker"], limit=body.get("limit", 10))
        return {"statusCode": 200, "body": json.dumps(result)}
    except (KeyError, ValueError) as exc:
        logger.error("news_search error: %s", exc)
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.error("news_search unexpected error: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
