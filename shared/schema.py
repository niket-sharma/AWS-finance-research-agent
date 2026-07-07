from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Snapshot(BaseModel):
    price: float
    day_change_pct: float
    range_52w: tuple[float, float]
    market_cap: float | None = None


class Fundamentals(BaseModel):
    revenue_ttm: float | None = None
    net_income_ttm: float | None = None
    gross_margin: float | None = None
    yoy_revenue_growth: float | None = None
    key_points: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _numbers_require_sources(self) -> Fundamentals:
        has_numbers = any(
            v is not None
            for v in (self.revenue_ttm, self.net_income_ttm, self.gross_margin, self.yoy_revenue_growth)
        )
        if has_numbers and not self.sources:
            raise ValueError("Fundamentals with populated numbers must have at least one source")
        return self


class NewsSentiment(BaseModel):
    score: float = 0.0
    label: Literal["bearish", "neutral", "bullish"] = "neutral"
    top_headlines: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    status: Literal["ok", "unavailable"] = "ok"


class Risk(BaseModel):
    annualized_vol: float
    max_drawdown: float
    beta: float
    composite: Literal["low", "moderate", "elevated", "high"]
    drivers: list[str] = Field(default_factory=list)


class Regime(BaseModel):
    label: Literal[
        "risk_on_uptrend",
        "choppy_late_cycle",
        "risk_off_downtrend",
        "high_vol_stress",
        "recovery",
    ]
    signals: dict[str, str] = Field(default_factory=dict)
    positioning_guidance: str


class Thesis(BaseModel):
    summary: str
    bull_points: list[str] = Field(default_factory=list)
    bear_points: list[str] = Field(default_factory=list)
    advisory_note: str


class ResearchNote(BaseModel):
    ticker: str
    as_of: datetime
    snapshot: Snapshot
    fundamentals: Fundamentals
    news_sentiment: NewsSentiment
    risk: Risk
    regime: Regime
    thesis: Thesis
    disclaimer: str = "Advisory only. Not investment advice. No orders are placed."
