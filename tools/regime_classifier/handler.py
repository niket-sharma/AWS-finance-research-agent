"""Market-regime classifier — §5.2 of spec.

Operates on the benchmark price series (SPY by default).
All math is deterministic and fully unit-tested.
Lambda entry point: lambda_handler(event, context).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_POSITIONING = {
    "risk_on_uptrend": (
        "Constructive backdrop; risk assets favored. Maintain diversified exposure."
    ),
    "choppy_late_cycle": (
        "Uneven conditions; selective positioning. Monitor breadth and credit spreads."
    ),
    "risk_off_downtrend": (
        "Defensive posture; favor quality and reduced beta. Preserve capital."
    ),
    "high_vol_stress": (
        "Elevated volatility; reduce position size. Avoid leverage. Reassess frequently."
    ),
    "recovery": (
        "Early recovery signals; gradual re-risking may be appropriate as trend confirms."
    ),
}


def _trend(prices: np.ndarray) -> str:
    """Price vs 50-day and 200-day SMA."""
    if len(prices) < 200:
        sma50 = float(np.mean(prices[-min(50, len(prices)):]))
        last = float(prices[-1])
        return "up" if last > sma50 else "down"
    sma50 = float(np.mean(prices[-50:]))
    sma200 = float(np.mean(prices[-200:]))
    last = float(prices[-1])
    if last > sma50 and last > sma200:
        return "up"
    if last < sma50 and last < sma200:
        return "down"
    return "mixed"


def _vol_percentile(prices: np.ndarray, short_window: int = 20) -> str:
    """20-day realized vol percentile vs trailing 1-year."""
    if len(prices) < short_window + 2:
        return "normal"
    log_returns = np.diff(np.log(prices.astype(float)))
    if len(log_returns) < short_window:
        return "normal"
    recent_vol = float(np.std(log_returns[-short_window:], ddof=1) * np.sqrt(252))
    year_window = min(252, len(log_returns))
    rolling_vols = [
        float(np.std(log_returns[max(0, i - short_window):i], ddof=1) * np.sqrt(252))
        for i in range(short_window, year_window + 1)
    ]
    if not rolling_vols:
        return "normal"
    pct = sum(v < recent_vol for v in rolling_vols) / len(rolling_vols)
    if pct > 0.80:
        return "elevated"
    if pct < 0.20:
        return "low"
    return "normal"


def _momentum(prices: np.ndarray, window: int = 63) -> str:
    """63-day (~3-month) return."""
    if len(prices) < window + 1:
        window = len(prices) - 1
    if window < 1:
        return "flat"
    ret = (prices[-1] - prices[-window]) / prices[-window]
    if ret > 0.02:
        return "positive"
    if ret < -0.02:
        return "negative"
    return "flat"


def _had_recent_drawdown(prices: np.ndarray, lookback: int = 63, threshold: float = -0.10) -> bool:
    """Check if there was a notable drawdown in the recent lookback window."""
    if len(prices) < lookback:
        lookback = len(prices)
    window = prices[-lookback:]
    peak = np.maximum.accumulate(window)
    dd = (window - peak) / peak
    return float(np.min(dd)) < threshold


def classify_regime(bench_prices: list[float]) -> dict[str, Any]:
    """Classify the current market regime from benchmark price series.

    Args:
        bench_prices: Daily adjusted-close prices for the benchmark (oldest first).

    Returns:
        dict with keys: label, signals, positioning_guidance.
    """
    if len(bench_prices) < 5:
        raise ValueError("bench_prices must have at least 5 points")

    prices = np.array(bench_prices, dtype=float)
    trend = _trend(prices)
    vol_state = _vol_percentile(prices)
    momentum = _momentum(prices)

    signals = {"trend": trend, "volatility": vol_state, "momentum": momentum}

    if vol_state == "elevated":
        label = "high_vol_stress"
    elif trend == "up" and momentum == "positive" and vol_state != "elevated":
        label = "risk_on_uptrend"
    elif trend == "down" and momentum == "negative":
        label = "risk_off_downtrend"
    elif trend == "mixed" and momentum in ("positive", "flat") and _had_recent_drawdown(prices):
        label = "recovery"
    else:
        label = "choppy_late_cycle"

    return {
        "label": label,
        "signals": signals,
        "positioning_guidance": _POSITIONING[label],
    }


def lambda_handler(event: dict, context: Any) -> dict:
    try:
        body = event if isinstance(event, dict) else json.loads(event)
        result = classify_regime(bench_prices=body["bench_prices"])
        return {"statusCode": 200, "body": json.dumps(result)}
    except (KeyError, ValueError) as exc:
        logger.error("regime_classifier error: %s", exc)
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.error("regime_classifier unexpected error: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
