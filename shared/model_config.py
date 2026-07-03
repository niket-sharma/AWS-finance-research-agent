"""Model IDs, caps, and caching config — one place for all agents."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCaps:
    model_id: str
    max_tool_calls: int
    max_tokens: int
    timeout_secs: int
    prompt_cache: bool = True


# Routing, planning, cheap tool-calling — Nova Micro
SUPERVISOR = ModelCaps(
    model_id="us.amazon.nova-micro-v1:0",
    max_tool_calls=20,
    max_tokens=4096,
    timeout_secs=60,
)

# Fundamentals / Market&Risk / News workers — Claude Haiku
WORKER = ModelCaps(
    model_id="us.anthropic.claude-haiku-4-5-20251001:0",
    max_tool_calls=10,
    max_tokens=4096,
    timeout_secs=90,
)

# Writer synthesis (only here) — Claude Sonnet
WRITER = ModelCaps(
    model_id="us.anthropic.claude-sonnet-4-6:20250514-v1:0",
    max_tool_calls=5,
    max_tokens=8192,
    timeout_secs=120,
)

# Eval judge — cheapest
JUDGE = ModelCaps(
    model_id="us.amazon.nova-micro-v1:0",
    max_tool_calls=5,
    max_tokens=2048,
    timeout_secs=60,
)

# Phase 0 single-agent (worker-tier)
SINGLE_AGENT = WORKER

AWS_REGION = "us-east-1"
CACHE_TABLE = "research-desk-cache"
CACHE_TTL_SECS = 3600  # 1 hour — market data freshness
