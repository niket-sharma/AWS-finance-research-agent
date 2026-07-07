"""Model IDs, caps, and caching config — one place for all agents.

All roles pinned to Nova Micro — the cheapest model available — by deliberate
choice (not the spec's tiered Nova/Haiku/Sonnet design). Per-role caps
(max_tool_calls, max_tokens, timeout) are kept distinct since they still
shape behavior even on a single model. Revisit WRITER if thesis quality
proves too weak on Nova Micro for the synthesis step.
"""

from dataclasses import dataclass

NOVA_MICRO = "us.amazon.nova-micro-v1:0"


@dataclass(frozen=True)
class ModelCaps:
    model_id: str
    max_tool_calls: int
    max_tokens: int
    timeout_secs: int
    prompt_cache: bool = True


# Routing, planning, cheap tool-calling
SUPERVISOR = ModelCaps(
    model_id=NOVA_MICRO,
    max_tool_calls=20,
    max_tokens=4096,
    timeout_secs=60,
)

# Fundamentals / Market&Risk / News workers
WORKER = ModelCaps(
    model_id=NOVA_MICRO,
    max_tool_calls=10,
    max_tokens=4096,
    timeout_secs=90,
)

# Writer synthesis (only here)
WRITER = ModelCaps(
    model_id=NOVA_MICRO,
    max_tool_calls=5,
    max_tokens=8192,
    timeout_secs=120,
)

# Eval judge — cheapest
JUDGE = ModelCaps(
    model_id=NOVA_MICRO,
    max_tool_calls=5,
    max_tokens=2048,
    timeout_secs=60,
)

# Phase 0 single-agent (worker-tier)
SINGLE_AGENT = WORKER

AWS_REGION = "us-east-1"
CACHE_TABLE = "research-desk-cache"
CACHE_TTL_SECS = 3600  # 1 hour — market data freshness
