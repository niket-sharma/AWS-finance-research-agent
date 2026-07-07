"""EDGAR filings tool — resolves ticker → CIK and lists recent 10-K/10-Q filings.

Uses SEC EDGAR submissions API (free, no API key). Requires a descriptive
User-Agent per SEC guidelines.

Lambda entry point: lambda_handler(event, context).
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from shared.cache import get as cache_get
    from shared.cache import put as cache_put
except ImportError:
    def cache_get(*_a, **_kw):
        return None
    def cache_put(*_a, **_kw):
        pass

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://data.sec.gov"
EDGAR_WWW_BASE = "https://www.sec.gov"
USER_AGENT = "research-desk/0.1 sharma.niket@gmail.com"
_CIK_CACHE: dict[str, str] = {}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _get(url: str) -> dict:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _resolve_cik(ticker: str) -> str | None:
    """Return zero-padded 10-digit CIK for ticker, or None if not found."""
    if ticker in _CIK_CACHE:
        return _CIK_CACHE[ticker]
    data = _get(f"{EDGAR_WWW_BASE}/files/company_tickers.json")
    for entry in data.values():
        if entry.get("ticker", "").upper() == ticker.upper():
            cik = str(entry["cik_str"]).zfill(10)
            _CIK_CACHE[ticker] = cik
            return cik
    return None


def get_filings(ticker: str, form_types: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
    """Return recent filings metadata for ticker.

    Args:
        ticker: Equity ticker symbol (e.g. "AAPL").
        form_types: List of form types to filter (default ["10-K", "10-Q"]).
        limit: Max number of recent filings to return.

    Returns:
        dict with keys: ticker, cik, filings (list of filing dicts).
    """
    if form_types is None:
        form_types = ["10-K", "10-Q"]

    today = date.today().isoformat()
    cache_key = f"filings:{','.join(form_types)}:{limit}"
    cached = cache_get(cache_key, ticker, today)
    if cached is not None:
        return cached

    cik = _resolve_cik(ticker)
    if cik is None:
        return {"ticker": ticker, "cik": None, "filings": [], "error": "CIK not found"}

    data = _get(f"{EDGAR_BASE}/submissions/CIK{cik}.json")
    recent = data.get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])

    results = []
    for form, filed, accession, doc in zip(forms, dates, accessions, docs):
        if form in form_types:
            acc_no_dashes = accession.replace("-", "")
            cik_no_zeros = str(int(cik))
            url = (
                f"https://www.sec.gov/Archives/edgar/data/"
                f"{cik_no_zeros}/{acc_no_dashes}/{doc}"
                if doc
                else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}"
            )
            results.append({
                "form": form,
                "filed": filed,
                "accession": accession,
                "url": url,
            })
        if len(results) >= limit:
            break

    result = {"ticker": ticker.upper(), "cik": cik, "filings": results}
    cache_put(cache_key, ticker, today, result)
    return result


def lambda_handler(event: dict, context: Any) -> dict:
    try:
        body = event if isinstance(event, dict) else json.loads(event)
        result = get_filings(
            ticker=body["ticker"],
            form_types=body.get("form_types"),
            limit=body.get("limit", 5),
        )
        return {"statusCode": 200, "body": json.dumps(result)}
    except (KeyError, ValueError) as exc:
        logger.error("edgar_filings error: %s", exc)
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.error("edgar_filings unexpected error: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
