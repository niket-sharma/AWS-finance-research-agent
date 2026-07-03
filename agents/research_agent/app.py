"""AgentCore Runtime entry point — wraps the research agent in BedrockAgentCoreApp.

Deployed as a container to AgentCore Runtime via:
    agentcore launch --entrypoint agents/research_agent/app.py

Local test:
    python agents/research_agent/app.py
"""

from __future__ import annotations

import json
import logging

from bedrock_agentcore import BedrockAgentCoreApp

from .agent import research

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()


@app.entrypoint
def handle(payload: dict, context) -> dict:
    """AgentCore Runtime entrypoint.

    Expected payload: {"ticker": "AAPL"}
    Returns: validated ResearchNote as JSON-serializable dict.
    """
    ticker = payload.get("ticker", "").strip().upper()
    if not ticker:
        return {"error": "ticker is required"}
    try:
        note = research(ticker)
        return note.model_dump(mode="json")
    except Exception as exc:
        logger.error("research failed for %s: %s", ticker, exc, exc_info=True)
        return {"error": str(exc), "ticker": ticker}


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    note = research(ticker)
    print(json.dumps(note.model_dump(mode="json"), indent=2))
