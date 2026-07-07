# Architecture, Run & Deploy Guide

Living reference for this repo — how the code fits together, how to run/test/debug it
locally, and how to deploy it to AWS. Update this file as new phases land; it should
always describe the *current* state of the code, not a history of how it got there
(that's what `progress.md` is for — session-by-session build log and decision history).

For one-time AWS account setup (IAM user, CLI config, CDK bootstrap, Bedrock model
access), see `aws-bedrock-agentcore-setup-guide.md`. For the full product spec and
phase-by-phase requirements, see `Agentcore-financial-research-spec.md`.

---

## 1. What this is

An AI research-desk agent that, given a ticker, produces a structured, schema-validated
`ResearchNote`: price snapshot, EDGAR-sourced fundamentals (grounded in filing text via
a Bedrock Knowledge Base), computed risk metrics, market regime classification, news
sentiment, and a synthesized thesis. Built in phases, each adding a production concern
(IaC, grounding, multi-agent orchestration, guardrails, observability) rather than
building the whole thing at once.

Currently deployed: **Phase 0** (single agent, all tools) and **Phase 1** (Knowledge
Base grounding). Phases 2–4 (multi-agent, guardrails/identity, eval/observability) are
spec'd but not built — see `Agentcore-financial-research-spec.md` for what they entail.

---

## 2. Code architecture

```
shared/
  schema.py         Pydantic models for the full ResearchNote (§4 of the spec)
  model_config.py    Which Bedrock model each role uses + token/timeout caps
  cache.py           DynamoDB read-through cache, keyed (tool, ticker, date)

tools/                One capability each; a pure function + a lambda_handler wrapper
  market_data/         yfinance — price snapshot + history
  risk_metrics/         Pure math — annualized vol, max drawdown, beta, composite rating
  regime_classifier/    Pure math — trend/vol/momentum → 5-label market regime
  edgar_filings/         SEC submissions API — ticker→CIK, recent 10-K/10-Q metadata
  edgar_company_facts/   SEC XBRL API — TTM revenue/net income/margins/growth
  news_search/           Finnhub — recent headlines (degrades gracefully, no key required)
  kb_retrieve/            Bedrock KB retrieve — grounding passages from ingested filings

agents/research_agent/
  agent.py            Strands Agent: wraps 7 tools as @tool functions, prompts the
                       model to call them and emit ResearchNote JSON, Pydantic-validates
  app.py               BedrockAgentCoreApp wrapper for eventual Runtime deployment

infra/
  phase0_runtime_gateway/stack.py   DynamoDB cache table + 6 tool Lambdas + IAM role
  phase1_knowledge_base/stack.py    S3 Vectors KB + kb_retrieve Lambda
  app.py                             CDK app entry point — both stacks, same account/region

knowledge/corpus/      Real 10-K filings (plain text) ingested into the KB
eval/golden_tickers.jsonl   Seed tickers + rubric for future eval work
tests/                 Unit tests — mocked AWS calls, no network/deploy needed
```

### Design choices worth knowing

- **Tools are plain Python functions with a `lambda_handler` wrapper**, not
  Lambda-only code. In Phase 0 the agent imports and calls the functions directly (no
  network hop) — this is why `research("AAPL")` works with zero AWS deploy for the tool
  layer. The *same* function also runs as a real Lambda once deployed (`market_data`,
  `kb_retrieve`, etc. are invoked in prod exactly as tested locally).
- **`compute_risk`/`classify_market_regime` fetch price history internally** — they
  take a ticker string, not raw price arrays. Earlier versions required the LLM to
  regenerate ~760 floats as tool-call arguments, which reliably blew the output token
  budget (`MaxTokensReachedException`) regardless of model. Never reintroduce
  "pass me the array" tool signatures for anything that can instead be looked up by key.
- **The agent prompt includes an explicit JSON shape template**
  (`RESEARCH_NOTE_TEMPLATE` in `agent.py`), not just "follow the schema." Smaller/cheaper
  models especially need the literal shape shown, not described.
- **All model roles are pinned to Nova Micro** (`shared/model_config.py`) — a deliberate
  cost choice, not the original spec's tiered Nova/Haiku/Sonnet design. It's also why no
  Bedrock model-access console step is needed (Nova Micro is Amazon's own model, already
  `AVAILABLE`; Anthropic models require a use-case form). If thesis quality proves too
  weak for the Writer role once Phase 2 exists, that's the first place to reconsider.
- **Cache and news-search degrade gracefully, never crash.** `shared/cache.py` catches
  `ClientError` and returns a miss; `news_search` returns `status="unavailable"` if no
  Finnhub key is configured. This is why you'll see `cache get/put failed` warnings in
  logs before Phase 0 is deployed (no DynamoDB table exists yet) — expected, not a bug.
- **`Fundamentals` numbers require sources.** A `model_validator` in `schema.py` rejects
  any populated `revenue_ttm`/`net_income_ttm`/`gross_margin`/`yoy_revenue_growth` if
  `sources` is empty — this is what makes grounding enforceable rather than aspirational.

---

## 3. Running and testing locally

```bash
source .venv/bin/activate        # venv already set up; if missing: make venv
```

**Unit tests** (fast, fully mocked, no AWS/network calls):
```bash
pytest tests/ -v
```

**Lint:**
```bash
ruff check .
```

**CDK synth** (validates infra code → CloudFormation, no AWS calls):
```bash
cd infra && cdk synth ResearchDeskPhase0 && cdk synth ResearchDeskPhase1
```

**Individual tools against live data** (no AWS needed — hits yfinance/SEC directly):
```bash
python -c "from tools.market_data.handler import get_snapshot; print(get_snapshot('AAPL'))"
python -c "from tools.edgar_filings.handler import get_filings; print(get_filings('AAPL', limit=1))"
python -c "from tools.kb_retrieve.handler import retrieve_passages; print(retrieve_passages('revenue growth', ticker='AAPL'))"
```
`kb_retrieve` returns `status: "unavailable"` unless `KB_ID` is set in the environment
(see §5 below for the real deployed value).

**Full agent smoke test:**
```bash
make smoke
# or directly:
python -c "from agents.research_agent.agent import research; print(research('AAPL'))"
```

---

## 4. Debugging

| Symptom | Cause | Fix |
|---|---|---|
| `cache get/put failed: ResourceNotFoundException` in logs | DynamoDB table doesn't exist yet (Phase 0 not deployed) | Expected pre-deploy; harmless. Deploy Phase 0 to make it go away. |
| `kb_retrieve` returns `status: "unavailable"` | `KB_ID` env var not set, or Phase 1 not deployed | Deploy Phase 1, then `export KB_ID=<KnowledgeBaseId from stack output>` before running the agent |
| `MaxTokensReachedException` from Strands | A tool is forcing the model to regenerate a large payload (e.g. raw price arrays) as output tokens | Redesign the tool to take a lookup key, not the raw data — see the `compute_risk` fix in §2 |
| `pydantic_core.ValidationError` on agent output | Model didn't follow the exact JSON shape (missing fields, wrong nesting, enum values used incorrectly) | Check `RESEARCH_NOTE_TEMPLATE` and the `CONSTRAINTS` block in `agent.py`'s `SYSTEM_PROMPT` are still accurate; add an explicit constraint for the failure mode you're seeing (this is exactly how the `news_sentiment.label`/`score` constraint got added) |
| `ResourceNotFoundException: Model use case details have not been submitted` | Trying to use an Anthropic model (Haiku/Sonnet) whose use-case form hasn't been accepted in the Bedrock console | Either accept the form (AWS Console → Bedrock → Model access, us-east-1), or use a model that doesn't require it (Nova Micro, Titan) |
| CDK deploy fails on a resource that depends on an IAM policy created in the same deploy | Classic race: the referencing resource only depends on the *Role*, not the *inline Policy* resource CloudFormation creates separately — they get created in parallel and the permission hasn't propagated yet | Use an explicit `iam.Policy` construct (not `role.add_to_policy`) and add an explicit `resource.node.add_dependency(policy)` — see `phase1_knowledge_base/stack.py`'s `KnowledgeBasePermissions` for the pattern |
| Bedrock KB ingestion job fails: `Filterable metadata must have at most 2048 bytes` | S3 Vectors caps *filterable* metadata at 2048 bytes/vector; Bedrock stores chunk text there by default | Set `non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]` on the `CfnIndex` — raises the cap to 40KB. This field requires index replacement (see next row). |
| CDK wants to *replace* the S3 Vectors index/KB/DataSource for a config change | Vector index config (e.g. `metadata_configuration`) is immutable in place, and the index has a fixed literal name, so create-before-delete replacement collides on the name | `cdk destroy ResearchDeskPhase1 --force` then `cdk deploy ResearchDeskPhase1` again, rather than fighting the in-place update — safe as long as nothing valuable is in the KB yet |

---

## 5. Deploying to AWS manually

Prerequisites: AWS CLI configured (`aws sts get-caller-identity` should show your IAM
user), CDK bootstrapped in the target account/region (one-time — see the setup guide).
This project deploys to account `911634252933`, region `us-east-1` (see `infra/app.py`).

```bash
source .venv/bin/activate

# 1. Build the Lambda layer (installs deps into layer/python/)
make layer

cd infra

# 2. Deploy Phase 0 — DynamoDB cache table + 6 tool Lambdas
cdk deploy ResearchDeskPhase0 --require-approval never

# 3. Deploy Phase 1 — S3 Vectors KB + kb_retrieve Lambda
cdk deploy ResearchDeskPhase1 --require-approval never
```

Step 3's output prints `KnowledgeBaseId` and `DataSourceId` — copy them for the next
step (values are regenerated per deploy, don't hardcode old ones):

```bash
# 4. Trigger KB ingestion — CloudFormation creates the DataSource resource but does
#    NOT auto-ingest; this is a required manual/scripted step every time the corpus
#    changes or the stack is redeployed from scratch.
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id <KnowledgeBaseId> \
  --data-source-id <DataSourceId> \
  --region us-east-1

# 5. Poll until status is COMPLETE (or FAILED — check failureReasons if so)
aws bedrock-agent get-ingestion-job \
  --knowledge-base-id <KnowledgeBaseId> \
  --data-source-id <DataSourceId> \
  --ingestion-job-id <ingestionJobId from step 4 output> \
  --region us-east-1
```

**Sanity checks after deploy:**
```bash
# A tool Lambda works
aws lambda invoke --function-name research-desk-market-data \
  --payload '{"ticker":"AAPL","action":"snapshot"}' \
  --cli-binary-format raw-in-base64-out /tmp/out.json --region us-east-1 && cat /tmp/out.json

# The KB retrieves real grounded passages
aws lambda invoke --function-name research-desk-kb-retrieve \
  --payload '{"query":"revenue growth drivers","ticker":"AAPL"}' \
  --cli-binary-format raw-in-base64-out /tmp/out2.json --region us-east-1 && cat /tmp/out2.json

# Full agent against the real deployed KB
KB_ID=<KnowledgeBaseId> python -c "from agents.research_agent.agent import research; print(research('AAPL'))"
```

**Tearing down** (see `infra/teardown.md` for the full checklist):
```bash
cd infra
cdk destroy ResearchDeskPhase1 ResearchDeskPhase0 --force
```

### Cost shape

Both stacks are pay-per-use, no idle minimums (`PAY_PER_REQUEST` DynamoDB, on-demand
Lambda, S3 Vectors instead of OpenSearch Serverless — the latter has a steep idle
minimum, which is why the spec mandates S3 Vectors). The only non-usage-gated cost is
Secrets Manager (~$0.40/mo per secret, only if you store the Finnhub key — currently
skipped). KB ingestion is a one-time per-run embedding cost, trivial for a corpus this
size. See `progress.md`'s Cost log for actual observed spend.

---

## 6. Current deployment state

Resource IDs are regenerated on every fresh deploy — treat the values below as "what it
looked like last time," not a live reference. Always read them from `cdk deploy` output
or `aws cloudformation describe-stacks` for the current truth.

- `ResearchDeskPhase0`: DynamoDB table `research-desk-cache`, Lambdas
  `research-desk-{market-data,risk-metrics,regime-classifier,edgar-filings,edgar-company-facts,news-search}`
- `ResearchDeskPhase1`: Knowledge Base, S3 Vectors bucket/index, corpus bucket, Lambda
  `research-desk-kb-retrieve`
- Corpus: 4 filings (AAPL, MSFT, NVDA, JPM 10-Ks), ingested and queryable

---

## 7. What's next

Phases 2–4 are spec'd in `Agentcore-financial-research-spec.md` but not built:

- **Phase 2** — multi-agent desk: Supervisor (A2A orchestration) fans out to
  Fundamentals/MarketRisk/NewsSentiment workers, a Writer agent synthesizes the final
  thesis, all 7 tools move behind an AgentCore Gateway as MCP targets.
- **Phase 3** — Bedrock Guardrails (denied topics, prompt-injection filter) + AgentCore
  Identity (auth-scoped tool calls).
- **Phase 4** — OTel observability, expanded eval set, AgentCore Recommendations loop.

Update the sections above as each phase lands — architecture diagram, new tools/agents,
new debugging entries, new deploy steps.
