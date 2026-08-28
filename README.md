# PA Compass

Evidence-grounded **prior-authorization intake workflow** (Forward Deployed
Engineering capstone). The app reviews a synthetic prior-authorization intake
packet, detects missing information, explains why it is missing, drafts
provider follow-up questions, routes the case, and keeps a human approval
step at every stage.

**Deterministic where possible. AI where useful. Human where necessary.**
The workflow is a fixed LangGraph state machine — `validate → policy match →
assess → route → gate` — with policy files as the source of truth. The LLM
never decides routing or policy; it only extracts evidence from free-text
notes and drafts follow-up questions.

## Requirements

- Python 3.11+
- An OpenAI API key (only needed for AI-assisted mode; the app also runs in
  deterministic baseline mode without one)

## Run it

```bash
# 1. Create and activate a virtual environment (Python 3.11+)
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your OpenAI API key
cp .env.example .env
#    then edit .env and set: OPENAI_API_KEY=sk-...

# 4. Launch the app
streamlit run app.py
```

Open http://localhost:8501 and log in as **Analyst** (daily case review) or
**ADMIN** (evaluation, audit, per-case workflow runs).

### Using any OpenAI-compatible endpoint

Set `LLM_BASE_URL` in `.env` to point at any OpenAI-compatible endpoint;
`LLM_MODEL` selects the model. Leave both blank for OpenAI defaults.

## Demo walkthrough

1. **Analyst desk** — "Welcome, John 👋". Every case shows the complete
   packet (facts, full clinical narrative, applied policy) before any
   decision. Yellow = AI marked it ready for sign-off; red = needs review.
2. **Follow-up loop** — a missing-info case shows the AI's drafted follow-up
   question, editable. **Send to provider** parks the case as awaiting
   response; **Simulate provider response (demo)** re-enters the supplemented
   packet and the workflow re-assesses it.
3. **Security cases** — prompt-injection packets are restricted (ADMIN-only
   detail) and escalated.
4. **ADMIN** — per-case runs (Static / AI Assisted), evaluation metrics and
   drift, and the full audit log.

## Data notice

All cases, patients, notes, and policies in `data/` and `policies/` are
**synthetic** — fictional payers, procedures, and no real PHI. Generated for
the capstone demo.

## Project layout

```
app.py                 Streamlit operations UI (analyst desk + admin dashboard)
pa_compass/            workflow (LangGraph), policy engine, LLM client, audit
policies/              synthetic policy definitions (source of truth)
data/                  synthetic intake packets, batch assessment, audit log, eval results
docs/                  submission package: problem brief, AI evidence, enterprise readiness, demo script
```
