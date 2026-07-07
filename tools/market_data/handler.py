"""Market data tool — provider-agnostic price history and snapshot.

Default backend: yfinance (free, no key). The interface is designed so
an alternative provider (Finnhub, Alpha Vantage, Tiingo) can be swapped
by changing the backend without touching the agent or risk tools.

Lambda entry point: lambda_handler(event, context).
"""
#Test deployment: aws lambda invoke --function-name market_data --payload '{"ticker": "AAPL"}' response.json
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

try:
    from shared.cache import get as cache_get
    from shared.cache import put as cache_put
except ImportError:
    def cache_get(*_a, **_kw):
        return None
    def cache_put(*_a, **_kw):
        pass

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "SPY"
PRICE_WINDOW_DAYS = 380  # slightly more than 252 trading days


def _fetch_yfinance(ticker: str, days: int) -> dict[str, Any]:
    import yfinance as yf
    end = date.today()
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(), progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data returned for {ticker}")
    closes = df["Close"].dropna()
    prices = [float(p) for p in closes.values.flatten()]
    info = {}
    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception:
        pass
    return {
        "prices": prices,
        "latest_price": prices[-1] if prices else None,
        "prev_close": prices[-2] if len(prices) >= 2 else None,
        "market_cap": info.get("marketCap"),
        "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
    }


def get_price_history(ticker: str, days: int = PRICE_WINDOW_DAYS) -> dict[str, Any]:
    """Return adjusted-close price series and snapshot for the ticker.

    Args:
        ticker: Equity or ETF ticker (e.g. "AAPL", "SPY").
        days: Calendar days of history to fetch.

    Returns:
        dict with prices, latest_price, prev_close, market_cap, 52w high/low.
    """
    today = date.today().isoformat()
    cached = cache_get("market_data", ticker, today)
    if cached is not None:
        return cached

    result = _fetch_yfinance(ticker, days)
    result["ticker"] = ticker.upper()
    result["as_of"] = today
    cache_put("market_data", ticker, today, result)
    return result


def get_snapshot(ticker: str) -> dict[str, Any]:
    """Return a price snapshot suitable for the ResearchNote.Snapshot section."""
    data = get_price_history(ticker)
    price = data.get("latest_price") or 0.0
    prev = data.get("prev_close") or price
    day_change_pct = ((price - prev) / prev * 100) if prev else 0.0
    hi = data.get("fifty_two_week_high") or price
    lo = data.get("fifty_two_week_low") or price
    return {
        "price": round(price, 2),
        "day_change_pct": round(day_change_pct, 4),
        "range_52w": (round(lo, 2), round(hi, 2)),
        "market_cap": data.get("market_cap"),
    }


def lambda_handler(event: dict, context: Any) -> dict:
    try:
        body = event if isinstance(event, dict) else json.loads(event)
        action = body.get("action", "history")
        ticker = body["ticker"]
        if action == "snapshot":
            result = get_snapshot(ticker)
        else:
            result = get_price_history(ticker, days=body.get("days", PRICE_WINDOW_DAYS))
        return {"statusCode": 200, "body": json.dumps(result, default=str)}
    except (KeyError, ValueError) as exc:
        logger.error("market_data error: %s", exc)
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.error("market_data unexpected error: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
