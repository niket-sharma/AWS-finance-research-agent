"""Unit tests for tools/risk_metrics — §5.1 deterministic math."""

import pytest

from tools.risk_metrics.handler import (
    _sub_score_beta,
    _sub_score_drawdown,
    _sub_score_vol,
    compute_risk_metrics,
)

# ── Sub-score thresholds ──────────────────────────────────────────────────────

@pytest.mark.parametrize("vol,expected", [
    (0.10, "low"),
    (0.199, "low"),
    (0.20, "moderate"),
    (0.30, "moderate"),
    (0.349, "moderate"),
    (0.35, "elevated"),
    (0.49, "elevated"),
    (0.50, "high"),
    (0.80, "high"),
])
def test_sub_score_vol(vol, expected):
    assert _sub_score_vol(vol) == expected


@pytest.mark.parametrize("mdd,expected", [
    (-0.05, "low"),
    (-0.14, "low"),
    (-0.15, "moderate"),
    (-0.25, "moderate"),
    (-0.30, "elevated"),
    (-0.49, "elevated"),
    (-0.50, "high"),
    (-0.80, "high"),
])
def test_sub_score_drawdown(mdd, expected):
    assert _sub_score_drawdown(mdd) == expected


@pytest.mark.parametrize("beta,expected", [
    (0.5, "low"),
    (0.79, "low"),
    (0.80, "moderate"),
    (1.0, "moderate"),
    (1.19, "moderate"),
    (1.20, "elevated"),
    (1.59, "elevated"),
    (1.60, "high"),
    (2.0, "high"),
])
def test_sub_score_beta(beta, expected):
    assert _sub_score_beta(beta) == expected


# ── Full computation ──────────────────────────────────────────────────────────

def _constant_prices(n: int, value: float = 100.0) -> list[float]:
    return [value] * n


def _trending_up(n: int, start: float = 100.0, daily_return: float = 0.001) -> list[float]:
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_return))
    return prices


def test_zero_vol_constant_prices():
    """Constant prices → zero vol, zero drawdown, zero beta."""
    asset = _constant_prices(100)
    bench = _constant_prices(100)
    result = compute_risk_metrics(asset, bench)
    assert result["annualized_vol"] == pytest.approx(0.0, abs=1e-6)
    assert result["max_drawdown"] == pytest.approx(0.0, abs=1e-6)
    assert result["beta"] == pytest.approx(0.0, abs=1e-6)
    assert result["composite"] == "low"
    assert isinstance(result["drivers"], list)


def test_drawdown_computed_correctly():
    """Prices that fall 30% from peak → max_drawdown ≈ -0.30."""
    prices = [100.0] * 50 + [70.0] * 50
    bench = _constant_prices(100)
    result = compute_risk_metrics(prices, bench)
    assert result["max_drawdown"] == pytest.approx(-0.30, abs=0.01)


def test_beta_positive_correlation():
    """Asset that moves 2× the benchmark → beta ≈ 2.0."""
    import numpy as np
    np.random.seed(42)
    bench_returns = np.random.normal(0, 0.01, 253)
    asset_returns = bench_returns * 2.0
    bench_prices = list(np.cumprod(1 + bench_returns) * 100)
    asset_prices = list(np.cumprod(1 + asset_returns) * 100)
    result = compute_risk_metrics(asset_prices, bench_prices)
    assert result["beta"] == pytest.approx(2.0, abs=0.05)


def test_beta_negative_correlation():
    """Asset that moves inversely to benchmark → beta negative."""
    import numpy as np
    np.random.seed(7)
    bench_returns = np.random.normal(0, 0.01, 253)
    asset_returns = -bench_returns
    bench_prices = list(np.cumprod(1 + bench_returns) * 100)
    asset_prices = list(np.cumprod(1 + asset_returns) * 100)
    result = compute_risk_metrics(asset_prices, bench_prices)
    assert result["beta"] < 0


def test_high_vol_composite():
    """High-vol asset → composite = 'high'."""
    import numpy as np
    np.random.seed(99)
    returns = np.random.normal(0, 0.04, 253)  # ~64% annualized vol
    prices = list(np.cumprod(1 + returns) * 100)
    bench = _constant_prices(253)
    result = compute_risk_metrics(prices, bench)
    assert result["composite"] == "high"
    assert "volatility" in result["drivers"]


def test_window_truncation():
    """Only the last `window` prices are used."""
    long_asset = _constant_prices(400, 100.0)
    long_bench = _constant_prices(400, 100.0)
    result_252 = compute_risk_metrics(long_asset, long_bench, window=252)
    result_100 = compute_risk_metrics(long_asset, long_bench, window=100)
    assert result_252["annualized_vol"] == result_100["annualized_vol"]


def test_minimum_length_validation():
    with pytest.raises(ValueError):
        compute_risk_metrics([100.0], [100.0])


def test_lambda_handler_valid():
    import json

    from tools.risk_metrics.handler import lambda_handler
    event = {
        "asset_prices": list(range(100, 200)),
        "bench_prices": list(range(100, 200)),
    }
    resp = lambda_handler(event, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "annualized_vol" in body


def test_lambda_handler_missing_key():

    from tools.risk_metrics.handler import lambda_handler
    resp = lambda_handler({}, None)
    assert resp["statusCode"] == 400
