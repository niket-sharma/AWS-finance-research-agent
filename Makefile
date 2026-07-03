.PHONY: venv layer test lint synth deploy-phase0 clean

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

venv:
	python3 -m venv $(VENV)
	$(PIP) install -r requirements-dev.txt

layer: venv
	@echo "Building Lambda layer..."
	$(PIP) install \
		boto3 requests numpy yfinance tenacity \
		--target layer/python \
		--quiet

test: venv
	$(VENV)/bin/pytest tests/ -v

lint: venv
	$(VENV)/bin/ruff check .

synth: layer
	cd infra && $(shell pwd)/.venv/bin/python app.py 2>&1 | head -5
	cd infra && cdk synth

deploy-phase0: layer
	cd infra && cdk deploy ResearchDeskPhase0 --require-approval never

smoke: venv
	$(PY) -c "from agents.research_agent.agent import research; note = research('AAPL'); print(note.ticker, note.snapshot.price)"

clean:
	rm -rf layer/python infra/cdk.out .pytest_cache __pycache__
