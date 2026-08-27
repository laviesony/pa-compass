# Problem Brief — PA Compass

**Target user:** Prior-authorization (PA) intake specialists and operations reviewers at a health plan. Their job: determine whether each incoming PA request packet contains the information required by the relevant procedure policy *before* the case proceeds to downstream clinical review.

**Workflow pain point:** Every packet is manually screened — required fields checked, document recency verified, thresholds compared, missing items identified, follow-ups drafted, and the case routed to the right queue. The task is repetitive and rules-based but high-consequence: a packet sent downstream incomplete wastes reviewer time; a packet rejected for missing paperwork delays care. Manual screening is slow (minutes per packet), inconsistent between reviewers, and scales linearly with volume.

**Value hypothesis:** If intake screening is assisted by a system that deterministically checks policy requirements, extracts evidence from free-text notes with an LLM, flags missing or conflicting information, drafts follow-up questions, and routes the case — while keeping every final decision with a human — then intake reviewers spend less time per packet and miss fewer missing-information items, without surrendering authority.

**Primary pilot success metric:** Median intake handling time (per packet).

**Guardrail metrics (must not regress):**
- Missing-information recall
- Incorrect routing rate
- Human override rate
- Unsupported recommendation rate
- Human escalation recall

**Constraints:**
- Synthetic data only — no PHI, no production data, no real patient/provider identities
- Entirely fictional procedure policies (the LLM is never the source of truth for policy)
- Human decision authority preserved; no autonomous authorization decisions
- Prototype evaluates intake completeness — it makes no medical-necessity or coverage determination
- Simple, runnable stack: Python + LangGraph + Streamlit, one CSV of sample packets, no external infrastructure

**Assumptions:**
- Intake completeness is a meaningful, separable step from clinical review (the workflow exists today in PA operations)
- An LLM API key (OpenAI-compatible) is available at run time; the system degrades gracefully to deterministic-only mode without one
- The 30-case labeled evaluation set included in this repo is representative of real intake variety (complete, missing, threshold, stale, conflicting, malformed, unknown-procedure, duplicate, ambiguous, adversarial, long-narrative packets)

**Prototype scope:** 5 fictional procedure policies · 40 synthetic packets (30 labeled eval cases) · deterministic policy engine + LLM evidence extraction · confidence gate · human approve/override/escalate in an operations UI · versioned evaluation runs and an audit log.
