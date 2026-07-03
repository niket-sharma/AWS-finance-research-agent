"""EDGAR company facts (XBRL) tool — pulls standardized financial metrics.

Uses SEC EDGAR companyfacts API (free, no key). Revenue, net income,
gross profit pulled directly from XBRL taxonomy.

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

try:
    from tools.edgar_filings.handler import EDGAR_BASE, USER_AGENT, _resolve_cik
except ImportError:
    from edgar_filings.handler import EDGAR_BASE, USER_AGENT, _resolve_cik

logger = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def _get(url: str) -> dict:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _latest_annual_value(facts: dict, taxonomy: str, concept: str) -> tuple[float | None, str | None]:
    """Extract the most recent annual (10-K) value for a concept."""
    try:
        units = facts["facts"][taxonomy][concept]["units"]
        usd_vals = units.get("USD", units.get("shares", []))
        annual = [v for v in usd_vals if v.get("form") in ("10-K", "10-K/A") and "val" in v]
        if not annual:
            return None, None
        latest = sorted(annual, key=lambda x: x.get("end", ""))[-1]
        return float(latest["val"]), latest.get("accn")
    except (KeyError, TypeError, IndexError):
        return None, None


def _ttm_value(facts: dict, taxonomy: str, concept: str) -> tuple[float | None, list[str]]:
    """Sum last 4 quarterly values for TTM (trailing twelve months)."""
    try:
        units = facts["facts"][taxonomy][concept]["units"]
        usd_vals = units.get("USD", [])
        quarterly = [
            v for v in usd_vals
            if v.get("form") in ("10-Q", "10-Q/A") and "val" in v
        ]
        if len(quarterly) < 4:
            return None, []
        sorted_q = sorted(quarterly, key=lambda x: x.get("end", ""))[-4:]
        ttm = sum(float(v["val"]) for v in sorted_q)
        sources = [v.get("accn", "") for v in sorted_q if v.get("accn")]
        return ttm, sources
    except (KeyError, TypeError):
        return None, []


def get_company_facts(ticker: str) -> dict[str, Any]:
    """Return key financial metrics from EDGAR XBRL for the given ticker.

    Args:
        ticker: Equity ticker (e.g. "AAPL").

    Returns:
        dict with revenue_ttm, net_income_ttm, gross_margin, yoy_revenue_growth, sources.
    """
    today = date.today().isoformat()
    cached = cache_get("edgar_company_facts", ticker, today)
    if cached is not None:
        return cached

    cik = _resolve_cik(ticker)
    if cik is None:
        return {"ticker": ticker, "error": "CIK not found", "sources": []}

    facts = _get(f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik}.json")

    rev_ttm, rev_sources = _ttm_value(facts, "us-gaap", "Revenues")
    if rev_ttm is None:
        rev_ttm, rev_sources_annual = _ttm_value(facts, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")
        rev_sources = rev_sources_annual or []

    ni_ttm, ni_sources = _ttm_value(facts, "us-gaap", "NetIncomeLoss")

    rev_prev, _ = _latest_annual_value(facts, "us-gaap", "Revenues")
    if rev_prev is None:
        rev_prev, _ = _latest_annual_value(facts, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")

    gross_profit_ttm, gp_sources = _ttm_value(facts, "us-gaap", "GrossProfit")
    gross_margin = None
    if gross_profit_ttm and rev_ttm and rev_ttm != 0:
        gross_margin = round(gross_profit_ttm / rev_ttm, 4)

    yoy = None
    if rev_ttm and rev_prev and rev_prev != 0:
        yoy = round((rev_ttm - rev_prev) / abs(rev_prev), 4)

    all_sources = list({s for s in rev_sources + ni_sources + gp_sources if s})

    result = {
        "ticker": ticker.upper(),
        "cik": cik,
        "revenue_ttm": rev_ttm,
        "net_income_ttm": ni_ttm,
        "gross_margin": gross_margin,
        "yoy_revenue_growth": yoy,
        "sources": all_sources,
    }
    cache_put("edgar_company_facts", ticker, today, result)
    return result


def lambda_handler(event: dict, context: Any) -> dict:
    try:
        body = event if isinstance(event, dict) else json.loads(event)
        result = get_company_facts(ticker=body["ticker"])
        return {"statusCode": 200, "body": json.dumps(result)}
    except (KeyError, ValueError) as exc:
        logger.error("edgar_company_facts error: %s", exc)
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.error("edgar_company_facts unexpected error: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
