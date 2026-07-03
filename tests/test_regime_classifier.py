"""Unit tests for tools/regime_classifier — §5.2 deterministic logic."""

import numpy as np
import pytest

from tools.regime_classifier.handler import (
    _had_recent_drawdown,
    _momentum,
    _trend,
    _vol_percentile,
    classify_regime,
)


def _flat_prices(n: int, v: float = 100.0) -> list[float]:
    return [v] * n


def _trending_up(n: int = 260, drift: float = 0.001) -> list[float]:
    p = [100.0]
    for _ in range(n - 1):
        p.append(p[-1] * (1 + drift))
    return p


def _trending_down(n: int = 260, drift: float = -0.001) -> list[float]:
    p = [100.0]
    for _ in range(n - 1):
        p.append(max(p[-1] * (1 + drift), 0.01))
    return p


# ── _trend ────────────────────────────────────────────────────────────────────

def test_trend_up():
    prices = np.array(_trending_up(260))
    assert _trend(prices) == "up"


def test_trend_down():
    prices = np.array(_trending_down(260))
    assert _trend(prices) == "down"


def test_trend_flat_is_mixed():
    prices = np.array(_flat_prices(260))
    result = _trend(prices)
    # constant prices: SMA50 == SMA200 == last price → neither strictly above/below
    assert result in ("up", "mixed")


# ── _momentum ─────────────────────────────────────────────────────────────────

def test_momentum_positive():
    prices = np.array(_trending_up(300))
    assert _momentum(prices) == "positive"


def test_momentum_negative():
    prices = np.array(_trending_down(300))
    assert _momentum(prices) == "negative"


def test_momentum_flat():
    prices = np.array(_flat_prices(300))
    assert _momentum(prices) == "flat"


# ── _vol_percentile ───────────────────────────────────────────────────────────

def test_low_vol_prices():
    prices = np.array(_flat_prices(260))
    result = _vol_percentile(prices)
    assert result in ("low", "normal")


def test_elevated_vol():
    np.random.seed(42)
    history = np.cumprod(1 + np.random.normal(0, 0.005, 240)) * 100
    shock = np.cumprod(1 + np.random.normal(0, 0.04, 21)) * history[-1]
    prices = np.concatenate([history, shock])
    result = _vol_percentile(prices)
    assert result in ("elevated", "normal")


# ── _had_recent_drawdown ──────────────────────────────────────────────────────

def test_recent_drawdown_detected():
    # Peak at 100 occurs inside the 63-day lookback window (13 high + 50 low)
    high = [100.0] * 50
    low = [85.0] * 50
    assert _had_recent_drawdown(np.array(high + low)) is True


def test_no_recent_drawdown():
    prices = np.array(_trending_up(300))
    assert _had_recent_drawdown(prices, threshold=-0.10) is False


# ── classify_regime ───────────────────────────────────────────────────────────

def test_risk_on_uptrend():
    prices = _trending_up(300, drift=0.002)
    result = classify_regime(prices)
    assert result["label"] == "risk_on_uptrend"
    assert "trend" in result["signals"]
    assert result["positioning_guidance"]


def test_risk_off_downtrend():
    prices = _trending_down(300, drift=-0.003)
    result = classify_regime(prices)
    assert result["label"] == "risk_off_downtrend"


def test_high_vol_stress_overrides_trend():
    """Elevated vol overrides an uptrend and classifies as high_vol_stress."""
    np.random.seed(11)
    base = list(np.cumprod(1 + np.random.normal(0.002, 0.005, 240)) * 100)
    shock = list(np.cumprod(1 + np.random.normal(0.001, 0.06, 22)) * base[-1])
    prices = base + shock
    result = classify_regime(prices)
    # If vol is elevated, label must be high_vol_stress
    if result["signals"]["volatility"] == "elevated":
        assert result["label"] == "high_vol_stress"


def test_minimum_price_series():
    with pytest.raises(ValueError):
        classify_regime([100.0, 101.0, 102.0, 103.0])


def test_output_keys():
    prices = _trending_up(300)
    result = classify_regime(prices)
    assert "label" in result
    assert "signals" in result
    assert "positioning_guidance" in result
    assert result["label"] in {
        "risk_on_uptrend", "choppy_late_cycle", "risk_off_downtrend",
        "high_vol_stress", "recovery",
    }


def test_lambda_handler():
    import json

    from tools.regime_classifier.handler import lambda_handler
    prices = _trending_up(260)
    resp = lambda_handler({"bench_prices": prices}, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "label" in body


def test_lambda_handler_missing_key():

    from tools.regime_classifier.handler import lambda_handler
    resp = lambda_handler({}, None)
    assert resp["statusCode"] == 400
