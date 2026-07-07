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
from tools.kb_retrieve.handler import retrieve_passages
from tools.market_data.handler import get_price_history, get_snapshot
from tools.news_search.handler import search_news
from tools.regime_classifier.handler import classify_regime
from tools.risk_metrics.handler import compute_risk_metrics

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a professional equity research analyst.
Given a ticker, you must:
1. Fetch the price snapshot.
2. Compute risk metrics for the ticker (pass only the ticker symbol — the tool
   fetches price history itself, do not fetch or restate raw price series).
3. Classify the market regime from the SPY benchmark (pass only the ticker symbol).
4. Fetch EDGAR company facts (XBRL financials).
5. Fetch recent EDGAR filings list.
6. Retrieve grounding passages from the filings knowledge base (e.g. query for
   revenue drivers, margin trends, risk factors) to write the fundamentals narrative.
7. Search for recent news headlines.
8. Produce a JSON ResearchNote following the schema exactly.

CONSTRAINTS:
- Never reference order execution, trading instructions, or specific investment recommendations.
- Every quantitative claim must come from a tool output.
- Never copy raw numeric arrays (e.g. price series) into your response — tools that need
  price history fetch it internally from just a ticker symbol.
- fundamentals.key_points must be grounded in retrieved KB passages or EDGAR data, not
  invented. fundamentals.sources must list the EDGAR accession numbers and/or KB passage
  source URIs actually used — never leave sources empty if any number is populated.
- If a section's data is unavailable, mark it as such rather than fabricating.
- If news is unavailable, set news_sentiment.status="unavailable" but still use valid
  values for the other fields: score=0.0 (never null) and label="neutral" (never
  "unavailable" — that word only belongs in the status field, not in label).
- Output ONLY valid JSON matching the ResearchNote schema — no prose, no markdown fences.
"""

RESEARCH_NOTE_TEMPLATE = """{
  "ticker": "<TICKER>",
  "as_of": "<ISO-8601 datetime>",
  "snapshot": {"price": <number>, "day_change_pct": <number>, "range_52w": [<number>, <number>], "market_cap": <number or null>},
  "fundamentals": {"revenue_ttm": <number or null>, "net_income_ttm": <number or null>, "gross_margin": <number or null>, "yoy_revenue_growth": <number or null>, "key_points": ["<plain string, NOT an object>", "..."], "sources": ["<accession number or KB source URI>", "..."]},
  "news_sentiment": {"score": <number>, "label": "bearish"|"neutral"|"bullish", "top_headlines": ["<string>", "..."], "sources": ["<string>", "..."], "status": "ok"|"unavailable"},
  "risk": {"annualized_vol": <number>, "max_drawdown": <number>, "beta": <number>, "composite": "low"|"moderate"|"elevated"|"high", "drivers": ["<string>", "..."]},
  "regime": {"label": "risk_on_uptrend"|"choppy_late_cycle"|"risk_off_downtrend"|"high_vol_stress"|"recovery", "signals": {"<key>": "<value>"}, "positioning_guidance": "<string>"},
  "thesis": {"summary": "<string>", "bull_points": ["<string>", "..."], "bear_points": ["<string>", "..."], "advisory_note": "<string>"}
}"""


@tool
def fetch_snapshot(ticker: str) -> str:
    """Fetch current price snapshot (price, day change, 52w range, market cap).

    Args:
        ticker: Equity or ETF ticker symbol.
    """
    return json.dumps(get_snapshot(ticker), default=str)


@tool
def compute_risk(ticker: str, benchmark: str = "SPY", days: int = 380) -> str:
    """Compute annualized vol, max drawdown, beta, and composite risk rating for a ticker.

    Fetches price history for the ticker and benchmark internally — do not pass
    raw price arrays; just name the tickers.

    Args:
        ticker: Equity or ETF ticker to assess.
        benchmark: Benchmark ticker for beta calculation (default SPY).
        days: Calendar days of history to use (default 380).
    """
    asset_prices = get_price_history(ticker, days=days).get("prices", [])
    bench_prices = get_price_history(benchmark, days=days).get("prices", [])
    return json.dumps(compute_risk_metrics(asset_prices, bench_prices))


@tool
def classify_market_regime(benchmark: str = "SPY", days: int = 380) -> str:
    """Classify the current market regime from benchmark price history.

    Fetches price history for the benchmark internally — do not pass raw price
    arrays; just name the benchmark ticker.

    Args:
        benchmark: Benchmark ticker to classify the regime from (default SPY).
        days: Calendar days of history to use (default 380).
    """
    bench_prices = get_price_history(benchmark, days=days).get("prices", [])
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
def fetch_kb_passages(query: str, ticker: str | None = None) -> str:
    """Retrieve grounding passages from the filings knowledge base for the fundamentals narrative.

    Args:
        query: Natural-language query, e.g. "revenue growth drivers" or "gross margin trends".
        ticker: Equity ticker symbol to scope the query.
    """
    return json.dumps(retrieve_passages(query, ticker=ticker), default=str)


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
            fetch_snapshot,
            compute_risk,
            classify_market_regime,
            fetch_company_facts,
            fetch_filings,
            fetch_kb_passages,
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
        "Use all available tools. Return only the JSON object, matching this exact "
        "shape (keys, nesting, and types) — do not add, rename, or nest fields "
        "differently, and do not turn any string-array field into an array of objects:\n"
        f"{RESEARCH_NOTE_TEMPLATE}"
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
