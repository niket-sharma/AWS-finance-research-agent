"""Risk metrics tool — §5.1 of spec.

All math is deterministic and fully unit-tested.
Lambda entry point: lambda_handler(event, context).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _sub_score_vol(vol: float) -> str:
    if vol < 0.20:
        return "low"
    if vol < 0.35:
        return "moderate"
    if vol < 0.50:
        return "elevated"
    return "high"


def _sub_score_drawdown(mdd: float) -> str:
    abs_mdd = abs(mdd)
    if abs_mdd < 0.15:
        return "low"
    if abs_mdd < 0.30:
        return "moderate"
    if abs_mdd < 0.50:
        return "elevated"
    return "high"


def _sub_score_beta(beta: float) -> str:
    abs_beta = abs(beta)
    if abs_beta < 0.8:
        return "low"
    if abs_beta < 1.2:
        return "moderate"
    if abs_beta < 1.6:
        return "elevated"
    return "high"


_SEVERITY = {"low": 0, "moderate": 1, "elevated": 2, "high": 3}
_LABEL = ["low", "moderate", "elevated", "high"]


def compute_risk_metrics(
    asset_prices: list[float],
    bench_prices: list[float],
    window: int = 252,
) -> dict[str, Any]:
    """Compute risk metrics from adjusted-close price series.

    Args:
        asset_prices: Daily adjusted-close prices for the asset (oldest first).
        bench_prices: Daily adjusted-close prices for the benchmark (same dates).
        window: Trailing days for computation (default 252 = 1 trading year).

    Returns:
        dict with keys: annualized_vol, max_drawdown, beta, composite, drivers.
    """
    if len(asset_prices) < 2 or len(bench_prices) < 2:
        raise ValueError("Price series must have at least 2 points")

    n = min(len(asset_prices), len(bench_prices), window)
    a = np.array(asset_prices[-n:], dtype=float)
    b = np.array(bench_prices[-n:], dtype=float)

    r_asset = np.diff(np.log(a))
    r_bench = np.diff(np.log(b))

    annualized_vol = float(np.std(r_asset, ddof=1) * np.sqrt(252))

    peaks = np.maximum.accumulate(a)
    drawdowns = (a - peaks) / peaks
    max_drawdown = float(np.min(drawdowns))

    var_bench = float(np.var(r_bench, ddof=1))
    if var_bench == 0:
        beta = 0.0
    else:
        beta = float(np.cov(r_asset, r_bench, ddof=1)[0, 1] / var_bench)

    scores = {
        "volatility": _sub_score_vol(annualized_vol),
        "drawdown": _sub_score_drawdown(max_drawdown),
        "beta": _sub_score_beta(beta),
    }
    worst = max(_SEVERITY[s] for s in scores.values())
    composite = _LABEL[worst]
    drivers = [k for k, v in scores.items() if _SEVERITY[v] == worst]

    return {
        "annualized_vol": round(annualized_vol, 4),
        "max_drawdown": round(max_drawdown, 4),
        "beta": round(beta, 4),
        "composite": composite,
        "drivers": drivers,
    }


def lambda_handler(event: dict, context: Any) -> dict:
    try:
        body = event if isinstance(event, dict) else json.loads(event)
        result = compute_risk_metrics(
            asset_prices=body["asset_prices"],
            bench_prices=body["bench_prices"],
            window=body.get("window", 252),
        )
        return {"statusCode": 200, "body": json.dumps(result)}
    except (KeyError, ValueError) as exc:
        logger.error("risk_metrics error: %s", exc)
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.error("risk_metrics unexpected error: %s", exc)
        return {"statusCode": 500, "body": json.dumps({"error": "internal error"})}
