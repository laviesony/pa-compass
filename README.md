# PA Compass

**Evidence-grounded prior-authorization intake workflow.**

PA Compass is an evidence-grounded prior-authorization intake orchestration system that identifies missing information, explains why it is missing, recommends the next workflow action, routes the case, and keeps humans in control. It reviews a synthetic prior-authorization intake packet, detects missing information, drafts follow-up questions, routes the case, and preserves a human approval step.

PA Compass is **not**:
- an autonomous authorization decision maker
- a clinical decision system
- a chatbot
- a free-running autonomous agent
- a replacement for human authorization reviewers

Design philosophy: **Deterministic where possible. AI where useful. Human where necessary.** The LangGraph workflow is a fixed state machine (`validate → policy match → assess → confidence gate`); synthetic policy files are the source of truth, and the LLM is confined to extracting evidence from free-text notes, drafting follow-up questions, and summarizing reasons.

## Quickstart

Requires **Python 3.11+** (macOS's system `python3` is 3.9 — use a 3.11+ interpreter or a venv).

```bash
# 1. Install dependencies (Python 3.11+)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. (Optional, for LLM-assisted mode) set an OpenAI-compatible key
cp .env.example .env        # then edit: LLM_API_KEY=sk-...
#     or export OPENAI_API_KEY / DEEPSEEK_API_KEY instead

# 3a. Run the operations UI
streamlit run app.py

# 3b. Or run the evaluation from the CLI
python scripts/process_cases.py --only-eval                # deterministic baseline
python scripts/process_cases.py --only-eval --llm          # full pipeline (LLM extraction)
```

Works with any OpenAI-compatible provider (`LLM_PROVIDER=openai|deepseek`, `LLM_MODEL`, optional `LLM_BASE_URL`). Without a key, the app and CLI still run in deterministic baseline mode.

## What's in the repo

```text
PAIWA/
├── app.py                     # Streamlit operations UI (queue, case review, eval, audit)
├── pa_compass/                # one small package
│   ├── models.py              # pydantic models + enums (packets, policies, results)
│   ├── policy_engine.py       # deterministic requirement checks, routing, confidence
│   ├── workflow.py            # LangGraph state machine (validate → … → confidence gate)
│   ├── llm_client.py          # OpenAI-compatible client (openai / deepseek)
│   ├── prompts.py             # versioned prompts (PROMPT_VERSION)
│   ├── evaluate.py            # evaluation metrics
│   ├── audit.py               # JSONL audit logger
│   └── version.py             # workflow / policy / prompt / model / eval-set versions
├── policies/policies.yaml     # 5 fictional procedure policies (source of truth)
├── scripts/
│   ├── generate_cases.py      # seeded synthetic dataset generator (reproducible)
│   └── process_cases.py       # CLI: run the workflow over cases + evaluation metrics
├── data/
│   ├── pa_cases.csv           # 40 synthetic packets (30 labeled eval cases, 11 case types)
│   ├── eval_results/          # versioned evaluation runs (performance over time)
│   └── audit_log.jsonl        # append-only audit trail (created at runtime)
└── docs/                      # submission documents
    ├── problem_brief.md       # one-page brief (component 1)
    ├── ai_evidence.md         # tool choices, eval cases, measured results, risks (component 3)
    ├── enterprise_readiness.md# data/access/audit/security/handoff (component 4)
    └── demo_script.md         # five-minute demo narrative (component 5)
```

## How it works

1. **Validate** — the packet is parsed leniently; malformed values and prompt-injection text are caught deterministically and routed to human triage.
2. **Policy match** — the procedure's fictional policy is selected; unknown procedures route to UNSUPPORTED_PROCEDURE.
3. **Assess** — deterministic checks (required fields, `minimum_weeks` thresholds, `max_age_days` recency, duplicates) plus LLM evidence extraction from the free-text note (schema-validated, one retry, fail-closed). Conflicts and low evidence coverage escalate to clinical review.
4. **Confidence gate** — an explainable score from observable signals (< 0.80 → HUMAN_REVIEW). The LLM never self-reports confidence.
5. **Human** — every recommendation is approved, overridden (reason required), or escalated in the UI; the decision is written to the audit log.

Every conclusion keeps decision provenance: what was concluded, why (policy rule), what evidence (packet vs policy value), and where it came from. The UI shows the event timeline and "What would change this recommendation?" for each missing item.

## Measured results (this repository)

| Metric | Deterministic baseline | Full pipeline (LLM) |
|---|---|---|
| Routing accuracy | 83.3% | **100%** |
| Status accuracy | 83.3% | **100%** |
| Missing-item precision | 100% | **100%** |
| Missing-item recall | 83.3% | 96.7% |
| Escalation recall | 58.3% | **100%** |
| Unsafe auto-route rate | 41.7% | **0%** |

30-case labeled golden set · 11 case types (complete, missing, threshold, stale, contradictory, malformed, unknown procedure, duplicate, ambiguous, prompt injection, long narrative). Every run is saved with its versions; see `data/eval_results/` and `docs/ai_evidence.md`.

## DATA NOTICE

All data, policies, patient identities, provider identities, clinical narratives, authorization cases, and operational metrics contained in this repository are **synthetically generated** for demonstration purposes. No production data, PHI, PII, customer data, proprietary authorization policy, internal source code, credentials, or internal system information was used in the development, testing, evaluation, or demonstration of this prototype. The system never determines medical necessity or coverage, and it never auto-approves an authorization.
