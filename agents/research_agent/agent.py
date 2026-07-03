"""Phase 0 single research agent — Strands-based, deployed via BedrockAgentCoreApp.

Calls all tools directly (no Gateway hop in Phase 0 local mode).
Phase 2 will swap the @tool wrappers for Gateway MCP endpoints.

Returns a Pydantic-validated ResearchNote.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or inside agents/
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strands import Agent, tool
from strands.models import BedrockModel

from shared.model_config import AWS_REGION, SINGLE_AGENT
from shared.schema import (
    ResearchNote,
)
from tools.edgar_company_facts.handler import get_company_facts
from tools.edgar_filings.handler import get_filings
from tools.market_data.handler import get_price_history, get_snapshot
from tools.news_search.handler import search_news
from tools.regime_classifier.handler import classify_regime
from tools.risk_metrics.handler import compute_risk_metrics

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a professional equity research analyst.
Given a ticker, you must:
1. Fetch the price snapshot and 1-year price history.
2. Fetch the SPY benchmark price history (for risk and regime calculations).
3. Compute risk metrics using the asset and benchmark prices.
4. Classify the market regime using the benchmark prices.
5. Fetch EDGAR company facts (XBRL financials).
6. Fetch recent EDGAR filings list.
7. Search for recent news headlines.
8. Produce a JSON ResearchNote following the schema exactly.

CONSTRAINTS:
- Never reference order execution, trading instructions, or specific investment recommendations.
- Every quantitative claim must come from a tool output.
- If a section's data is unavailable, mark it as such rather than fabricating.
- Output ONLY valid JSON matching the ResearchNote schema — no prose, no markdown fences.
"""


@tool
def fetch_price_history(ticker: str, days: int = 380) -> str:
    """Fetch adjusted-close price history for a ticker.

    Args:
        ticker: Equity or ETF ticker symbol (e.g. AAPL, SPY).
        days: Calendar days of history (default 380).
    """
    result = get_price_history(ticker, days=days)
    return json.dumps(result, default=str)


@tool
def fetch_snapshot(ticker: str) -> str:
    """Fetch current price snapshot (price, day change, 52w range, market cap).

    Args:
        ticker: Equity or ETF ticker symbol.
    """
    return json.dumps(get_snapshot(ticker), default=str)


@tool
def compute_risk(asset_prices: list, bench_prices: list) -> str:
    """Compute annualized vol, max drawdown, beta, and composite risk rating.

    Args:
        asset_prices: Daily adjusted-close prices for the asset (oldest first).
        bench_prices: Daily adjusted-close prices for the benchmark (oldest first).
    """
    return json.dumps(compute_risk_metrics(asset_prices, bench_prices))


@tool
def classify_market_regime(bench_prices: list) -> str:
    """Classify the current market regime from benchmark price series (SPY).

    Args:
        bench_prices: Daily adjusted-close prices for the benchmark (oldest first).
    """
    return json.dumps(classify_regime(bench_prices))


@tool
def fetch_company_facts(ticker: str) -> str:
    """Fetch XBRL financial facts from SEC EDGAR (revenue, net income, margins).

    Args:
        ticker: Equity ticker symbol.
    """
    return json.dumps(get_company_facts(ticker), default=str)


@tool
def fetch_filings(ticker: str) -> str:
    """Fetch recent 10-K and 10-Q filing metadata from SEC EDGAR.

    Args:
        ticker: Equity ticker symbol.
    """
    return json.dumps(get_filings(ticker), default=str)


@tool
def fetch_news(ticker: str) -> str:
    """Fetch recent news headlines for a ticker.

    Args:
        ticker: Equity ticker symbol.
    """
    return json.dumps(search_news(ticker), default=str)


def _build_agent() -> Agent:
    model = BedrockModel(
        model_id=SINGLE_AGENT.model_id,
        region_name=AWS_REGION,
        max_tokens=SINGLE_AGENT.max_tokens,
    )
    return Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            fetch_price_history,
            fetch_snapshot,
            compute_risk,
            classify_market_regime,
            fetch_company_facts,
            fetch_filings,
            fetch_news,
        ],
    )


def research(ticker: str) -> ResearchNote:
    """Run the research agent for a given ticker and return a validated ResearchNote.

    Args:
        ticker: Equity ticker symbol (e.g. "AAPL").

    Returns:
        A Pydantic-validated ResearchNote.

    Raises:
        ValueError: If the agent output cannot be parsed into ResearchNote.
    """
    agent = _build_agent()
    prompt = (
        f"Produce a complete ResearchNote JSON for ticker: {ticker.upper()}. "
        "Use all available tools. Return only the JSON object."
    )
    raw = agent(prompt)
    raw_text = str(raw)

    # Strip any markdown fences the model might add despite instructions
    if "```" in raw_text:
        parts = raw_text.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped.startswith("{"):
                raw_text = stripped
                break

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        # Try to extract JSON object from mixed text
        import re
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise ValueError(f"Agent output is not valid JSON: {exc}") from exc

    # Ensure required datetime field
    if "as_of" not in data or not data["as_of"]:
        data["as_of"] = datetime.now(timezone.utc).isoformat()

    return ResearchNote.model_validate(data)
