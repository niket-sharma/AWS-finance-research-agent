"""Tests for shared/schema.py — Pydantic model validation."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.schema import (
    Fundamentals,
    NewsSentiment,
    Regime,
    ResearchNote,
    Risk,
    Snapshot,
)


def _valid_note() -> dict:
    return {
        "ticker": "AAPL",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "snapshot": {
            "price": 180.5,
            "day_change_pct": 1.2,
            "range_52w": [120.0, 200.0],
            "market_cap": 2_800_000_000_000,
        },
        "fundamentals": {
            "revenue_ttm": 394_000_000_000,
            "net_income_ttm": 97_000_000_000,
            "gross_margin": 0.44,
            "yoy_revenue_growth": 0.08,
            "key_points": ["Strong services growth"],
            "sources": ["0000320193-24-000006"],
        },
        "news_sentiment": {
            "score": 0.3,
            "label": "bullish",
            "top_headlines": ["Apple beats earnings"],
            "sources": ["reuters.com"],
            "status": "ok",
        },
        "risk": {
            "annualized_vol": 0.25,
            "max_drawdown": -0.28,
            "beta": 1.1,
            "composite": "moderate",
            "drivers": ["volatility"],
        },
        "regime": {
            "label": "risk_on_uptrend",
            "signals": {"trend": "up", "volatility": "normal", "momentum": "positive"},
            "positioning_guidance": "Constructive backdrop.",
        },
        "thesis": {
            "summary": "AAPL remains a quality compounder.",
            "bull_points": ["Services growth", "Buybacks"],
            "bear_points": ["China exposure", "Valuation"],
            "advisory_note": "Advisory only.",
        },
    }


def test_valid_research_note():
    note = ResearchNote.model_validate(_valid_note())
    assert note.ticker == "AAPL"
    assert note.disclaimer == "Advisory only. Not investment advice. No orders are placed."


def test_default_disclaimer():
    note = ResearchNote.model_validate(_valid_note())
    assert "Not investment advice" in note.disclaimer


def test_snapshot_required_fields():
    with pytest.raises(ValidationError):
        Snapshot.model_validate({"price": 100.0})  # missing day_change_pct and range_52w


def test_news_sentiment_unavailable_status():
    ns = NewsSentiment(status="unavailable")
    assert ns.score == 0.0
    assert ns.label == "neutral"


def test_risk_invalid_composite():
    with pytest.raises(ValidationError):
        Risk.model_validate({
            "annualized_vol": 0.2,
            "max_drawdown": -0.1,
            "beta": 1.0,
            "composite": "very_high",  # invalid literal
        })


def test_regime_invalid_label():
    with pytest.raises(ValidationError):
        Regime.model_validate({
            "label": "bullish",  # not a valid Regime label
            "positioning_guidance": "...",
        })


def test_fundamentals_nullable_fields():
    f = Fundamentals(revenue_ttm=None, net_income_ttm=None)
    assert f.revenue_ttm is None
    assert f.sources == []


def test_fundamentals_numbers_without_sources_rejected():
    with pytest.raises(ValidationError):
        Fundamentals(revenue_ttm=394_000_000_000, sources=[])


def test_fundamentals_numbers_with_sources_ok():
    f = Fundamentals(revenue_ttm=394_000_000_000, sources=["0000320193-24-000006"])
    assert f.revenue_ttm == 394_000_000_000


def test_research_note_serialization():
    note = ResearchNote.model_validate(_valid_note())
    data = note.model_dump(mode="json")
    assert isinstance(data["snapshot"]["range_52w"], list)
    assert len(data["snapshot"]["range_52w"]) == 2


def test_missing_ticker_raises():
    d = _valid_note()
    del d["ticker"]
    with pytest.raises(ValidationError):
        ResearchNote.model_validate(d)
