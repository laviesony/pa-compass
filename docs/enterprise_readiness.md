# Enterprise Readiness — PA Compass

## Data classification
- **All data in this repository is synthetic.** Packet contents, patient aliases, provider identifiers, clinical narratives, procedure policies, and operational metrics are generated for demonstration (see DATA NOTICE in README).
- The system is designed for **non-PHI intake metadata** in a production pilot. Assumption stated explicitly: this prototype never ingests, stores, or logs PHI/PII. A production deployment would classify packets as *internal + sensitive* and add field-level encryption at rest; that is out of scope here by design.

## Access needs
- **Role-based access assumption (least privilege):**
  - *Intake reviewer* — view assigned cases, run the workflow, approve/override/escalate recommendations.
  - *Clinical reviewer* — cases routed to CLINICAL_REVIEW; can request more documentation.
  - *Admin/operator* — manage policy versions, view eval results, audit log.
  - *Model API* — service credential (LLM_API_KEY) held by the app runtime, never by end users, never committed.
- The Streamlit prototype implements a single-user session; the access model above is the documented target for pilot.

## Audit / logging
- **Append-only JSONL audit log** (`data/audit_log.jsonl`): every case processed and every human decision (approve / override with mandatory reason / escalate) is recorded with timestamp, case id, system recommendation, and decision.
- **Model-call telemetry**: per-invocation stats (model, prompt version, tokens, latency, retries, schema validity) captured into workflow events — never raw clinical note text, never keys.
- **Versioned evaluation runs** (`data/eval_results/*.json`): each run records workflow/prompt/policy/model/eval-set versions and full per-case results, enabling regression comparison over time.
- **Retention assumption**: audit records retained per health-plan policy (e.g. 7 years for authorization records); the prototype retains everything for the demo session.

## Security / compliance controls
- Secrets only via environment / `.env` (gitignored); `.env.example` documents keys; no credentials in the repo.
- **Prompt-injection defense**: packet text is treated as untrusted data — deterministic detection in the workflow (never rely on the LLM alone) plus explicit instruction hierarchy in the extraction prompt; adversarial cases are part of the eval set.
- **Structured output + schema validation**: all LLM output validated with Pydantic; one controlled retry, then fail-closed to HUMAN_REVIEW (never silent fallback).
- **Evidence grounding**: LLM-claimed missing items are filtered against the actual policy requirements; ungrounded claims are dropped and logged.
- **Fail-closed routing**: malformed packets, unknown procedures, duplicates, conflicts, and low confidence all escalate to a human; the system never auto-approves and never determines coverage.
- **Compliance assumption**: for a US health-plan pilot this touches HIPAA-adjacent workflows; the prototype contains no PHI by construction, which is the primary control demonstrated here. A production deployment would add SOC 2-type controls, role-based auth, encryption, and sign-off by the compliance owner.

## Handoff owner
- **Named role: Intake Operations Lead / Workflow Owner** (health plan side) — owns the pilot, the policy catalog (with clinical/legal review before any real policy is encoded), the eval set, and decisions to promote the workflow to new procedures.
- **Engineering owner: Forward Deployed Engineer** — maintains the repo, prompt versions, model configuration, eval harness, and monitors guardrail metrics (missing-info recall, routing accuracy, override rate).
- What the handoff needs (documented in README + ai_evidence.md): setup steps, versioned eval runs, the audit log, and this readiness note.
