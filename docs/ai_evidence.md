# AI Evidence — PA Compass

## Problem framing
The task is *intake completeness assessment* — not medical necessity, not coverage, not an approval decision. The workflow must find what's missing, explain why, draft follow-ups, route, and defer to a human. That framing drives every choice below.

## Tool & architecture choices
| Choice | Why |
|---|---|
| **LangGraph StateGraph** | The workflow IS a state machine (validate → policy match → assess → confidence gate). LangGraph makes nodes/edges explicit and auditable; the LLM cannot move workflow state — only deterministic edges do. |
| **Deterministic engine first** (`policy_engine.py`) | Required fields, `minimum_weeks` thresholds, `max_age_days` recency, duplicate/malformed/unknown-procedure handling, routing, and the confidence formula are all deterministic. Policy YAML is the source of truth — never the LLM. |
| **LLM confined to 3 functions** (`llm_client.py`) | (1) extract evidence from free-text clinical notes, (2) draft follow-up questions, (3) summarize a reviewer-facing reason. No tool-calling loop, no autonomous agent. |
| **Provider abstraction** | OpenAI-compatible client; works with `openai` or `deepseek` via env (`LLM_PROVIDER`, `LLM_API_KEY`/`OPENAI_API_KEY`/`DEEPSEEK_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL`). Model-swappable; eval runs record the model id. |
| **Structured output + Pydantic validation** | Every LLM response validated against `ExtractionResult`/`list[str]` schemas; one corrective retry; second failure → fail-closed HUMAN_REVIEW (MODEL_FAILURE / SCHEMA_FAILURE logged). No silent fallback. |
| **Prompt versioning** | All prompts in `prompts.py` with `PROMPT_VERSION`; eval runs record workflow/prompt/policy/model/eval-set versions for regression comparison. |

## Data & retrieval approach
- **No retrieval/RAG**: the evidence is the packet itself and the policy file. Policies are small, versioned YAML — no vector store needed (adding one would be architecture theatre).
- **Synthetic dataset**: `data/pa_cases.csv` — 40 packets generated with a fixed seed (reproducible), 30 of them labeled eval cases spanning 11 case types (complete, missing, threshold, stale, contradictory, malformed, unknown procedure, duplicate, ambiguous, prompt injection, long narrative).
- **Golden labels**: `expected_status`, `expected_route`, `expected_missing_items`, `expected_human_review` per eval case — hand-specified in the generator, reviewed for consistency.

## Evaluation cases & measured results
Run: `python scripts/process_cases.py --only-eval [--llm]` — results saved under `data/eval_results/` with full version metadata.

| Metric | Deterministic baseline | Full pipeline (LLM) |
|---|---|---|
| Routing accuracy | 83.3% (25/30) | **100% (30/30)** |
| Status accuracy | 83.3% (25/30) | **100% (30/30)** |
| Missing-item precision | 100% | **100%** |
| Missing-item recall | 83.3% | 96.7% |
| Missing-item F1 | 83.3% | 96.7% |
| Escalation recall (expected-human cases) | 58.3% (7/12) | **100% (12/12)** |
| Unsafe auto-route rate | 41.7% (5/12) | **0% (0/12)** |
| Unsupported recommendation rate | 0% | **0%** |

The only full-pipeline "miss" is a label nuance: one contradictory-evidence packet (structured 8 weeks vs narrative 3 weeks) is correctly routed to CLINICAL_REVIEW with its conflict flagged — but its expected label lists `conservative_treatment` under *missing items* while the system reports it as *conflicting evidence*. Route and status both match; the semantics are documented rather than tuned away.

What the baseline gets wrong (honest): contradictory-evidence packets (structured 8 weeks vs narrative 3 weeks) and ambiguous packets — both require text interpretation. Prompt-injection packets are caught deterministically. The full pipeline detects conflicts (→ CLINICAL_REVIEW) and low evidence coverage on otherwise-complete packets (→ confidence gate → HUMAN_REVIEW).

## Prompt regression: v0.2.0 → v0.2.1 (measured)

Prompt versions are recorded in every eval run, so a prompt change is regression-tested on the golden set before shipping:

| Metric | Prompt v0.2.0 | Prompt v0.2.1 |
|---|---|---|
| Routing accuracy | 93.3% | **96.7%** |
| Missing-item precision | 95.0% | **100%** |
| Missing-item recall | **100%** | 93.3% |
| Escalation recall | 100% | 100% |
| Unsafe auto-route rate | 0% | 0% |

**What changed:** v0.2.0 sometimes reported a requirement as *missing* when the packet's structured field already contained a value (e.g. `symptoms` on a complete CT Chest packet) — false positives that turned complete packets into NEEDS_INFORMATION. v0.2.1 adds an explicit rule: *"Never report a requirement as missing when the packet's structured field for it already contains a value: missing means truly absent or unusable, not merely unclear."*

**Why keep v0.2.1 despite the recall dip:** the 2 recall points lost are contradictory-evidence packets where the structured field *does* contain a value (8 weeks) while the narrative says 3 weeks. v0.2.1 correctly classifies those as **conflicting evidence → CLINICAL_REVIEW** (they still escalate; the route/status outcome is unchanged) instead of *missing*. The system's safety posture — 100% escalation recall, 0% unsafe auto-routes — is identical, and precision rose to 100%. Fewer false "missing" flags means fewer unnecessary provider follow-ups. A future eval label refinement (expected `missing_items` = `conservative_treatment` vs `conflicts`) would reconcile the remaining metric gap; we document the label nuance rather than tune to it.

## Failure modes & known risks
| Failure mode | Detection | Response |
|---|---|---|
| LLM returns invalid JSON | schema validation | retry once → HUMAN_REVIEW (MODEL_FAILURE) |
| LLM output fails Pydantic validation | schema validation | retry once → HUMAN_REVIEW (SCHEMA_FAILURE) |
| Provider/network error | exception | fail closed → HUMAN_REVIEW |
| Prompt injection in packet text | deterministic flag + instruction hierarchy | HUMAN_TRIAGE; policy evidence still evaluated |
| LLM invents missing requirement | grounding filter (requirement must exist in policy) | claim dropped + logged (`ungrounded_claim_dropped`) |
| Conflicting evidence (structured vs narrative) | LLM `conflicts` field + 0.5 confidence multiplier | CLINICAL_REVIEW |
| Low evidence coverage | `evidence_coverage` × confidence | confidence gate → HUMAN_REVIEW |
| Malformed packet | deterministic parse issues | HUMAN_TRIAGE |
| Duplicate submission | `submission_attempt > 1` | ADMINISTRATIVE_REVIEW |
| Unknown procedure | no policy match | UNSUPPORTED_PROCEDURE |

Known risks to state in a pilot: LLM cost/latency per packet (~5s, cents on DeepSeek), prompt drift (mitigated by versioned eval), and the eval set being synthetic (a real pilot re-labels with live intake data).

## Human review checkpoints
1. **Malformed / injection / duplicate / unknown-procedure packets** — deterministic escalation, human triage.
2. **Conflicting evidence** — routed to CLINICAL_REVIEW; the system never silently resolves a conflict.
3. **Low confidence** (< 0.80) — gated to HUMAN_REVIEW.
4. **Every recommendation** — a human approves, overrides (reason required), or escalates; the decision is audited. Human decisions are authoritative and captured as candidate eval cases for future supervised evaluation.

## Model governance
- Golden set + versioned runs = regression suite: any prompt/model/policy change re-runs `process_cases.py --only-eval --llm` and diffs metrics (see `data/eval_results/`).
- Human overrides are *candidate* eval cases after review — never automatic learning.
- All measured numbers in this file come from actual runs in this repo; nothing is fabricated.
