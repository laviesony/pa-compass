"""PA Compass operations UI for synthetic prior-authorization intake."""

from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from pa_compass.audit import AuditLogger
from pa_compass.llm_client import LLMClient
from pa_compass.models import (
    CasePacket,
    MissingItem,
    PolicyDefinition,
    PolicyRequirement,
    WorkflowState,
    load_policies,
    packet_from_row,
)
from pa_compass.version import POLICY_VERSION, PROMPT_VERSION, WORKFLOW_VERSION
from pa_compass.workflow import build_graph, run_packet


st.set_page_config(page_title="PA Compass", layout="wide")

ROOT = Path(__file__).resolve().parent
CASE_PATH = ROOT / "data" / "pa_cases.csv"
BATCH_PATH = ROOT / "data" / "batch_assessment.json"
EVAL_PATH = ROOT / "data" / "eval_results"
POLICY_PATH = ROOT / "policies" / "policies.yaml"

load_dotenv(ROOT / ".env")
audit = AuditLogger(str(ROOT / "data" / "audit_log.jsonl"))
policies = load_policies(POLICY_PATH)
policy_by_code = {policy.procedure: policy for policy in policies}


@st.cache_data(show_spinner=False)
def load_cases(path: str) -> pd.DataFrame:
    """Load the intake queue once per CSV version."""

    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _inject_theme() -> None:
    """Apply the shared PA Compass visual language to both roles."""

    st.markdown(
        """
        <style>
        :root,
        [data-testid="stAppViewContainer"],
        [data-testid="stApp"],
        .stApp {
          color-scheme: light !important;
          --pa-teal: #095f87;
          --pa-teal-dark: #074a6b;
          --pa-charcoal: #1f1f1f;
          --pa-muted: #3d3c38;
          --pa-page: #f6f7f8;
          --pa-border: #e3e6e8;
          --pa-border-dark: #c9ced2;
          --pa-yellow: #f2b705;
          --pa-red: #d64545;
          --pa-green: #1e9e5a;
        }

        .stApp {
          background-color: var(--pa-page) !important;
          color: var(--pa-charcoal) !important;
        }

        [data-testid="stHeader"] {
          background-color: var(--pa-page) !important;
        }

        [data-testid="stSidebar"] {
          background-color: #ffffff !important;
          border-right: 1px solid var(--pa-border) !important;
        }
        [data-testid="stSidebar"] > div:first-child {
          padding-top: 1.4rem;
        }

        .pa-brand {
          padding: 0.25rem 0.15rem 1.2rem;
          border-bottom: 1px solid var(--pa-border);
          margin-bottom: 1rem;
        }
        .pa-brand-name {
          color: var(--pa-teal);
          font-size: 1.45rem;
          font-weight: 750;
          letter-spacing: -0.02em;
        }
        .pa-brand-caption {
          color: var(--pa-muted);
          font-size: 0.78rem;
          margin-top: 0.16rem;
        }

        /* Typography */
        h1, h2, h3, h4, h5, h6 {
          color: var(--pa-charcoal) !important;
          letter-spacing: -0.02em;
        }
        p, span, label, li {
          color: var(--pa-charcoal);
        }
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p,
        .stCaption {
          color: var(--pa-muted) !important;
        }

        /* ==========================================================================
           Buttons (Default, Primary, Action Variants)
           ========================================================================== */

        /* Default / Secondary buttons */
        .stButton > button,
        button[kind="secondary"],
        button[data-testid="baseButton-secondary"],
        button[data-testid="stBaseButton-secondary"],
        .stButton button {
          background-color: #ffffff !important;
          border: 1px solid var(--pa-border-dark) !important;
          color: var(--pa-charcoal) !important;
          font-weight: 600 !important;
          border-radius: 0.45rem !important;
          box-shadow: 0 1px 2px rgba(31, 31, 31, 0.04) !important;
          transition: all 0.15s ease-in-out !important;
        }

        .stButton > button:hover,
        button[kind="secondary"]:hover,
        button[data-testid="baseButton-secondary"]:hover,
        button[data-testid="stBaseButton-secondary"]:hover,
        .stButton button:hover {
          background-color: #eef1f3 !important;
          border-color: #b0b7bc !important;
          color: var(--pa-charcoal) !important;
        }

        .stButton > button:active,
        .stButton > button:focus:not(:active),
        button[kind="secondary"]:active,
        button[kind="secondary"]:focus:not(:active) {
          background-color: #e6eaed !important;
          border-color: var(--pa-teal) !important;
          color: var(--pa-charcoal) !important;
          outline: none !important;
          box-shadow: 0 0 0 2px rgba(9, 95, 135, 0.2) !important;
        }

        .stButton > button:disabled,
        button:disabled,
        button[disabled] {
          background-color: #f6f7f8 !important;
          border-color: var(--pa-border) !important;
          color: #8b959b !important;
          cursor: not-allowed !important;
          opacity: 0.65 !important;
          box-shadow: none !important;
        }

        /* Primary buttons */
        .stButton > button[kind="primary"],
        button[kind="primary"],
        button[data-testid="baseButton-primary"],
        button[data-testid="stBaseButton-primary"],
        .stButton button[kind="primary"] {
          background-color: var(--pa-teal) !important;
          border: 1px solid var(--pa-teal) !important;
          color: #ffffff !important;
          font-weight: 600 !important;
          border-radius: 0.45rem !important;
          box-shadow: 0 1px 2px rgba(9, 95, 135, 0.15) !important;
        }

        .stButton > button[kind="primary"]:hover,
        button[kind="primary"]:hover,
        button[data-testid="baseButton-primary"]:hover,
        button[data-testid="stBaseButton-primary"]:hover,
        .stButton button[kind="primary"]:hover {
          background-color: var(--pa-teal-dark) !important;
          border-color: var(--pa-teal-dark) !important;
          color: #ffffff !important;
        }

        .stButton > button[kind="primary"]:active,
        .stButton > button[kind="primary"]:focus:not(:active),
        button[kind="primary"]:active,
        button[kind="primary"]:focus:not(:active) {
          background-color: #053750 !important;
          border-color: #053750 !important;
          color: #ffffff !important;
          outline: none !important;
          box-shadow: 0 0 0 2px rgba(9, 95, 135, 0.3) !important;
        }

        /* Approve action buttons (Analyst & Admin) */
        div[class*="st-key-analyst-approve"] button,
        div[class*="st-key-analyst_approve"] button,
        div[class*="st-key-approve"] button,
        div[class*="st-key-approve_"] button,
        div[data-testid*="analyst-approve"] button,
        div[data-testid*="approve-"] button,
        div[data-testid*="stKey-approve"] button {
          background-color: var(--pa-green) !important;
          border: 1px solid var(--pa-green) !important;
          color: #ffffff !important;
        }

        div[class*="st-key-analyst-approve"] button:hover,
        div[class*="st-key-analyst_approve"] button:hover,
        div[class*="st-key-approve"] button:hover,
        div[class*="st-key-approve_"] button:hover,
        div[data-testid*="analyst-approve"] button:hover,
        div[data-testid*="approve-"] button:hover,
        div[data-testid*="stKey-approve"] button:hover {
          background-color: #167f49 !important;
          border-color: #167f49 !important;
          color: #ffffff !important;
        }

        /* Reject action buttons (Analyst) */
        div[class*="st-key-analyst-reject"] button,
        div[class*="st-key-analyst_reject"] button,
        div[data-testid*="analyst-reject"] button {
          background-color: #ffffff !important;
          border: 1px solid var(--pa-red) !important;
          color: var(--pa-red) !important;
        }

        div[class*="st-key-analyst-reject"] button:hover,
        div[class*="st-key-analyst_reject"] button:hover,
        div[data-testid*="analyst-reject"] button:hover {
          background-color: #fff0f0 !important;
          border-color: var(--pa-red) !important;
          color: #8c2929 !important;
        }

        /* ==========================================================================
           Tabs
           ========================================================================== */
        [data-testid="stTabs"] {
          background-color: transparent !important;
        }
        [data-testid="stTabs"] [role="tablist"] {
          gap: 0.25rem;
          border-bottom: 2px solid var(--pa-border) !important;
        }
        [data-testid="stTabs"] button[role="tab"],
        button[data-baseweb="tab"],
        [data-testid="stTabs"] button {
          background-color: transparent !important;
          color: var(--pa-charcoal) !important;
          font-weight: 600 !important;
          font-size: 0.95rem !important;
          border: none !important;
          border-bottom: 2px solid transparent !important;
          margin-bottom: -2px !important;
          padding: 0.55rem 1rem !important;
          border-radius: 0.35rem 0.35rem 0 0 !important;
          opacity: 1 !important;
          transition: all 0.15s ease-in-out;
        }
        [data-testid="stTabs"] button[role="tab"] p,
        button[data-baseweb="tab"] p,
        [data-testid="stTabs"] button[role="tab"] span,
        button[data-baseweb="tab"] span,
        [data-testid="stTabs"] button[role="tab"] div,
        button[data-baseweb="tab"] div {
          color: var(--pa-charcoal) !important;
          font-weight: 600 !important;
        }
        [data-testid="stTabs"] button[role="tab"]:hover,
        button[data-baseweb="tab"]:hover {
          background-color: #eef1f3 !important;
          color: var(--pa-teal) !important;
        }
        [data-testid="stTabs"] button[role="tab"]:hover p,
        button[data-baseweb="tab"]:hover p,
        [data-testid="stTabs"] button[role="tab"]:hover span,
        button[data-baseweb="tab"]:hover span {
          color: var(--pa-teal) !important;
        }
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"],
        button[data-baseweb="tab"][aria-selected="true"] {
          background-color: transparent !important;
          color: var(--pa-teal) !important;
          border-bottom: 2px solid var(--pa-teal) !important;
          font-weight: 750 !important;
        }
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] p,
        button[data-baseweb="tab"][aria-selected="true"] p,
        [data-testid="stTabs"] button[role="tab"][aria-selected="true"] span,
        button[data-baseweb="tab"][aria-selected="true"] span {
          color: var(--pa-teal) !important;
          font-weight: 750 !important;
        }

        /* ==========================================================================
           Form Controls (Inputs, Selectboxes, Radio, Checkboxes, Pills)
           ========================================================================== */
        .stTextInput input,
        .stTextArea textarea,
        div[data-baseweb="input"] input,
        div[data-baseweb="textarea"] textarea,
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea {
          background-color: #ffffff !important;
          color: var(--pa-charcoal) !important;
          border: 1px solid var(--pa-border-dark) !important;
          border-radius: 0.375rem !important;
          -webkit-text-fill-color: var(--pa-charcoal) !important;
        }
        .stTextInput input::placeholder,
        .stTextArea textarea::placeholder {
          color: #8b959b !important;
          -webkit-text-fill-color: #8b959b !important;
        }
        .stTextInput input:focus,
        .stTextArea textarea:focus,
        div[data-baseweb="input"]:focus-within,
        div[data-baseweb="textarea"]:focus-within {
          border-color: var(--pa-teal) !important;
          box-shadow: 0 0 0 1px var(--pa-teal) !important;
        }

        [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        div[data-baseweb="select"] > div {
          background-color: #ffffff !important;
          color: var(--pa-charcoal) !important;
          border: 1px solid var(--pa-border-dark) !important;
          border-radius: 0.375rem !important;
        }
        [data-testid="stSelectbox"] div[data-baseweb="select"] span,
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] div {
          color: var(--pa-charcoal) !important;
        }
        div[data-baseweb="popover"],
        ul[data-baseweb="menu"],
        div[data-baseweb="menu"] {
          background-color: #ffffff !important;
        }
        ul[data-baseweb="menu"] li,
        div[data-baseweb="menu"] li,
        div[data-baseweb="menu"] div {
          background-color: #ffffff !important;
          color: var(--pa-charcoal) !important;
        }
        ul[data-baseweb="menu"] li:hover,
        div[data-baseweb="menu"] li:hover {
          background-color: #f1f4f5 !important;
          color: var(--pa-teal) !important;
        }

        [data-testid="stRadio"] label,
        [data-testid="stRadio"] div[role="radiogroup"] label {
          color: var(--pa-charcoal) !important;
        }
        [data-testid="stRadio"] label p,
        [data-testid="stRadio"] label span,
        [data-testid="stRadio"] label div {
          color: var(--pa-charcoal) !important;
        }
        [data-testid="stRadio"] > label {
          color: var(--pa-charcoal) !important;
          font-weight: 600 !important;
        }

        [data-testid="stCheckbox"] label,
        [data-testid="stCheckbox"] label p,
        [data-testid="stCheckbox"] label span {
          color: var(--pa-charcoal) !important;
        }

        [data-testid="stPills"] button,
        [data-testid="stSegmentedControl"] button {
          background-color: #ffffff !important;
          color: var(--pa-charcoal) !important;
          border: 1px solid var(--pa-border-dark) !important;
        }
        [data-testid="stPills"] button p,
        [data-testid="stSegmentedControl"] button p,
        [data-testid="stPills"] button span,
        [data-testid="stSegmentedControl"] button span {
          color: var(--pa-charcoal) !important;
        }
        [data-testid="stPills"] button:hover,
        [data-testid="stSegmentedControl"] button:hover {
          background-color: #eef1f3 !important;
          border-color: #b0b7bc !important;
          color: var(--pa-charcoal) !important;
        }
        [data-testid="stPills"] button[aria-selected="true"],
        [data-testid="stSegmentedControl"] button[aria-selected="true"],
        [data-testid="stPills"] button[data-checked="true"],
        [data-testid="stSegmentedControl"] button[data-checked="true"] {
          background-color: var(--pa-teal) !important;
          border-color: var(--pa-teal) !important;
          color: #ffffff !important;
        }
        [data-testid="stPills"] button[aria-selected="true"] p,
        [data-testid="stSegmentedControl"] button[aria-selected="true"] p,
        [data-testid="stPills"] button[data-checked="true"] p,
        [data-testid="stSegmentedControl"] button[data-checked="true"] p,
        [data-testid="stPills"] button[aria-selected="true"] span,
        [data-testid="stSegmentedControl"] button[aria-selected="true"] span,
        [data-testid="stPills"] button[data-checked="true"] span,
        [data-testid="stSegmentedControl"] button[data-checked="true"] span {
          color: #ffffff !important;
        }

        /* ==========================================================================
           Metrics, Cards, Alerts, Pills & Tables
           ========================================================================== */
        [data-testid="stMetric"] {
          background: #ffffff;
          border: 1px solid var(--pa-border);
          border-radius: 0.55rem;
          padding: 0.8rem 1rem;
          box-shadow: 0 1px 2px rgba(31, 31, 31, 0.03);
        }
        [data-testid="stMetricLabel"] { color: var(--pa-muted) !important; }
        [data-testid="stMetricValue"] { color: var(--pa-charcoal) !important; }

        .stat-card {
          background: #ffffff;
          border: 1px solid var(--pa-border);
          border-left: 5px solid var(--pa-teal);
          border-radius: 0.55rem;
          padding: 0.72rem 1rem 0.8rem;
          min-height: 5.2rem;
          box-shadow: 0 1px 2px rgba(31, 31, 31, 0.03);
        }
        .stat-card.stat-red { border-left-color: var(--pa-red); }
        .stat-card.stat-yellow { border-left-color: var(--pa-yellow); }
        .stat-card.stat-green { border-left-color: var(--pa-green); }
        .stat-label { color: var(--pa-muted); font-size: 0.82rem; }
        .stat-value { color: var(--pa-charcoal); font-size: 1.8rem; font-weight: 720; line-height: 1.2; }

        .section-bar {
          background: var(--pa-teal);
          border-radius: 0.42rem 0.42rem 0 0;
          color: #ffffff;
          font-size: 0.95rem;
          font-weight: 700;
          padding: 0.62rem 0.85rem;
          margin: 1.2rem 0 0;
        }

        .pill {
          border-radius: 999px;
          display: inline-block;
          font-size: 0.69rem;
          font-weight: 800;
          letter-spacing: 0.04em;
          line-height: 1;
          padding: 0.37rem 0.58rem;
          white-space: nowrap;
        }
        .pill-yellow { background: #fff3c4 !important; color: #765600 !important; }
        .pill-red { background: #fbe1e1 !important; color: #9c2d2d !important; }
        .pill-green { background: #dff5e8 !important; color: #146c3d !important; }
        .pill-neutral { background: #edf0f2 !important; color: var(--pa-muted) !important; }

        .attention-box {
          background: #fffaf0;
          border: 1px solid #f2d88c;
          border-left: 5px solid var(--pa-yellow);
          border-radius: 0.45rem;
          padding: 0.9rem 1.1rem;
          margin: 0.45rem 0 1rem;
        }
        .security-banner {
          background: #fff0f0;
          border: 1px solid #efb6b6;
          border-left: 6px solid var(--pa-red);
          border-radius: 0.45rem;
          color: #8c2929;
          font-size: 1.15rem;
          font-weight: 720;
          padding: 1rem 1.1rem;
          margin: 0.55rem 0 1rem;
        }

        .case-note {
          background: #ffffff;
          border: 1px solid var(--pa-border);
          border-left: 5px solid var(--pa-teal);
          border-radius: 0.45rem;
          color: var(--pa-charcoal);
          font-size: 0.88rem;
          line-height: 1.6;
          margin: 0.35rem 0 1rem;
          max-height: 340px;
          overflow-y: auto;
          padding: 0.9rem 1.1rem;
          white-space: pre-wrap;
        }

        .awaiting-box {
          background: #eef4f7;
          border: 1px solid #c8d9e2;
          border-left: 5px solid var(--pa-teal);
          border-radius: 0.45rem;
          color: #0b3d57;
          padding: 0.9rem 1.1rem;
          margin: 0.45rem 0 0.6rem;
        }

        .analyst-table-wrap {
          background: #ffffff;
          border: 1px solid var(--pa-border);
          border-top: 0;
          border-radius: 0 0 0.42rem 0.42rem;
          overflow-x: auto;
        }
        .analyst-table {
          border-collapse: collapse;
          min-width: 980px;
          width: 100%;
        }
        .analyst-table th {
          background: #f1f4f5;
          color: var(--pa-muted);
          font-size: 0.74rem;
          font-weight: 750;
          padding: 0.7rem 0.72rem;
          text-align: left;
          white-space: nowrap;
        }
        .analyst-table td {
          border-top: 1px solid #edf0f1;
          color: var(--pa-charcoal);
          font-size: 0.83rem;
          padding: 0.7rem 0.72rem;
          vertical-align: middle;
        }
        .analyst-table tr:hover td { background: #fafcfc; }
        .review-check { color: var(--pa-green); font-size: 1.05rem; font-weight: 800; }
        .review-nav { color: var(--pa-muted); padding-top: 0.55rem; text-align: center; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _resolved_llm_config() -> tuple[str, bool]:
    model = os.getenv("LLM_MODEL") or "gpt-4o-mini"
    has_key = any(
        bool(os.getenv(name))
        for name in ("OPENAI_API_KEY", "LLM_API_KEY")
    )
    return model, has_key


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _text_value(value: Any) -> str:
    if value is None or value == "":
        return "not present"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(_value(value))


def _pct(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return str(value)


def _pretty_number(value: float | int) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


def _evidence_for_requirement(
    packet: CasePacket, requirement: PolicyRequirement
) -> tuple[str, str]:
    path = requirement.key
    value = getattr(packet, requirement.key, None)
    if requirement.key == "clinical_note" and requirement.max_age_days is not None:
        path = "clinical_note_date"
        value = packet.clinical_note_date
    elif requirement.key == "conservative_treatment" and requirement.minimum_weeks:
        path = "treatment_duration_weeks"
        value = packet.treatment_duration_weeks
    return path, _text_value(value)


def _counterfactual(requirement: PolicyRequirement) -> str:
    if requirement.minimum_weeks is not None:
        return (
            f"Documentation showing ≥ {_pretty_number(requirement.minimum_weeks)} "
            f"weeks of {requirement.label}"
        )
    if requirement.max_age_days is not None:
        return f"A clinical note no older than {requirement.max_age_days} days"
    return f"Provide {requirement.label}"


def _status_pill(label: str, tone: str) -> str:
    return (
        f'<span class="pill pill-{html.escape(tone)}">'
        f"{html.escape(label)}</span>"
    )


def _render_status(
    state: dict[str, Any],
    display_status: str | None = None,
    tone: str | None = None,
    detail: str | None = None,
) -> None:
    status = str(_value(state.get("status")) or "UNKNOWN")
    route = str(_value(state.get("route")) or "UNROUTED")
    confidence = float(state.get("confidence") or 0.0)
    status_tones = {
        "READY": "yellow",
        "NEEDS_INFORMATION": "yellow",
        "HUMAN_REVIEW": "red",
        "ERROR": "red",
        "APPROVED": "green",
    }
    selected_tone = tone or status_tones.get(status, "neutral")
    colors = {
        "yellow": ("#fffaf0", "#765600", "#f2b705"),
        "red": ("#fff0f0", "#8c2929", "#d64545"),
        "green": ("#edf8f1", "#146c3d", "#1e9e5a"),
        "neutral": ("#f0f2f3", "#3d3c38", "#8b959b"),
    }
    background, foreground, accent = colors.get(
        selected_tone, colors["neutral"]
    )
    label = display_status or status.replace("_", " ")
    detail_html = (
        f'<div style="color:{foreground}; font-size:0.96rem; margin-top:0.48rem;">'
        f"{html.escape(detail)}</div>"
        if detail
        else ""
    )
    st.markdown(
        f"""
        <div style="background:{background}; border-left:6px solid {accent};
                    border-radius:8px; padding:18px 22px; margin:8px 0 20px;">
          <div style="color:{foreground}; font-size:1.55rem; font-weight:750;">
            {_status_pill(label, selected_tone)}
          </div>
          <div style="color:{foreground}; font-size:1rem; margin-top:4px;">
            Route: <strong>{html.escape(route.replace('_', ' '))}</strong>
            &nbsp;&nbsp;|&nbsp;&nbsp;
            Confidence: <strong>{confidence:.1%}</strong>
          </div>
          {detail_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_checklist(
    packet: CasePacket,
    policy: PolicyDefinition | None,
    state: dict[str, Any],
) -> None:
    st.subheader("Requirements checklist")
    if policy is None:
        st.warning("No matching policy is available for this procedure.")
        return

    assessment = state.get("assessment")
    missing_items = assessment.missing_items if assessment is not None else []
    missing_by_key = {item.requirement: item for item in missing_items}
    events = state.get("events", [])
    flagged = (
        _value(state.get("status")) == WorkflowState.HUMAN_REVIEW
        or bool(state.get("issues"))
        or any(
            event.get("type")
            in {
                "conflicting_evidence",
                "model_failure",
                "schema_failure",
                "prompt_injection_detected",
            }
            for event in events
        )
    )

    for requirement in policy.requirements:
        missing: MissingItem | None = missing_by_key.get(requirement.key)
        if missing is not None:
            icon, label, reason = "✕", "missing", missing.reason
            path = missing.evidence_path or requirement.key
            evidence = missing.evidence_value
        elif flagged:
            icon, label = "!", "flagged"
            reason = "Evidence is present, but this recommendation requires human review."
            path, evidence = _evidence_for_requirement(packet, requirement)
        else:
            icon, label = "✓", "satisfied"
            reason = "Policy requirement is supported by packet evidence."
            path, evidence = _evidence_for_requirement(packet, requirement)
        st.markdown(
            f"**{icon} {requirement.label}** · {label}  "
            f"  \n{reason}  "
            f"  \nEvidence: `{path}` = `{_text_value(evidence)}`"
        )


def _render_provenance(events: list[dict[str, Any]]) -> None:
    st.subheader("Decision provenance")
    timeline = [
        {
            "ts": event.get("ts", ""),
            "node": event.get("node") or event.get("type") or "event",
            "status": _value(event.get("status")) or "",
            "route": _value(event.get("route")) or "",
        }
        for event in events
    ]
    if timeline:
        st.dataframe(pd.DataFrame(timeline), use_container_width=True, hide_index=True)
    else:
        st.info("No workflow events recorded.")


def _recommendation_details(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(_value(state.get("status")) or "UNKNOWN"),
        "route": str(_value(state.get("route")) or "UNROUTED"),
        "confidence": float(state.get("confidence") or 0.0),
    }


def _record_human_decision(
    packet: CasePacket,
    state: dict[str, Any],
    decision: str,
    override_reason: str | None = None,
) -> None:
    audit.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "case_id": packet.case_id,
            "event": "human_decision",
            "details": {
                "decision": decision,
                "override_reason": override_reason,
                "system_recommendation": _recommendation_details(state),
            },
        }
    )


def _render_human_actions(
    packet: CasePacket, state: dict[str, Any]
) -> None:
    st.subheader("Human actions")
    approve, override, escalate = st.columns(3)
    with approve:
        approve_clicked = st.button(
            "Approve recommendation",
            type="primary",
            key=f"approve-{packet.case_id}",
            use_container_width=True,
        )
    with override:
        override_clicked = st.button(
            "Override", key=f"override-{packet.case_id}",
            use_container_width=True,
        )
    with escalate:
        escalate_clicked = st.button(
            "Escalate", key=f"escalate-{packet.case_id}",
            use_container_width=True,
        )
    if override_clicked:
        st.session_state[f"override_open-{packet.case_id}"] = True

    override_key = f"override_open-{packet.case_id}"
    if st.session_state.get(override_key):
        reason = st.text_input(
            "override_reason (required)", key=f"override-reason-{packet.case_id}"
        )
        confirm = st.button(
            "Confirm override",
            type="primary",
            key=f"confirm-override-{packet.case_id}",
        )
        if confirm:
            if not reason.strip():
                st.error("An override reason is required.")
            else:
                _record_human_decision(packet, state, "override", reason.strip())
                st.session_state[override_key] = False
                st.success("Override recorded in the audit log.")
    elif approve_clicked:
        _record_human_decision(packet, state, "approve")
        st.success("Recommendation approval recorded in the audit log.")
    elif escalate_clicked:
        _record_human_decision(packet, state, "escalate")
        st.success("Escalation recorded in the audit log.")


def _render_case_review(
    cases: pd.DataFrame,
    mode: str,
) -> None:
    case_ids = cases["case_id"].tolist()
    selected_case_id = st.selectbox("Select a case", case_ids)
    selected_row = cases.loc[cases["case_id"] == selected_case_id].iloc[0]
    packet, issues = packet_from_row(selected_row.to_dict())
    policy = policy_by_code.get(packet.procedure_code)

    st.caption(
        f"{packet.patient_alias or 'Unknown patient'} · "
        f"{packet.procedure_name or packet.procedure_code} · "
        f"Request date: {_text_value(packet.request_date)}"
    )
    if issues:
        st.warning("Packet parsing issues: " + "; ".join(issues))

    if st.button("Run workflow", type="primary", use_container_width=False):
        try:
            model, has_key = _resolved_llm_config()
            if mode == "LLM extraction":
                if not has_key:
                    raise ValueError(
                        "No OpenAI API key found. Set OPENAI_API_KEY in .env "
                        "or the environment."
                    )
                graph = build_graph(LLMClient(model=model))
            else:
                graph = build_graph()
            state = run_packet(packet, issues, graph=graph)
            st.session_state[f"state-{packet.case_id}"] = state
            audit.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "case_id": packet.case_id,
                    "event": "case_processed",
                    "details": {
                        "mode": "llm" if mode == "LLM extraction" else "baseline",
                        **_recommendation_details(state),
                    },
                }
            )
            st.success("Workflow completed.")
        except Exception as exc:
            st.error(
                "Workflow failed. Check the API key/provider configuration and "
                f"try again. Details: {exc}"
            )

    state = st.session_state.get(f"state-{packet.case_id}")
    if state is None:
        st.info("Run the workflow to view the recommendation and provenance.")
        return

    _render_status(state)
    _render_checklist(packet, state.get("policy") or policy, state)

    st.subheader("Follow-up questions draft")
    questions = state.get("follow_up_questions", [])
    if questions:
        for question in questions:
            st.markdown(f"- {question}")
    else:
        st.caption("No follow-up questions generated by this workflow run.")

    st.subheader("What would change this recommendation?")
    assessment = state.get("assessment")
    missing_items = assessment.missing_items if assessment is not None else []
    requirement_by_key = {
        requirement.key: requirement
        for requirement in (state.get("policy") or policy).requirements
    } if (state.get("policy") or policy) is not None else {}
    if missing_items:
        for item in missing_items:
            requirement = requirement_by_key.get(item.requirement)
            if requirement is not None:
                st.markdown(f"- {_counterfactual(requirement)}")
            else:
                st.markdown(f"- Provide {item.requirement}")
    else:
        st.caption("No missing requirement is currently driving the recommendation.")

    _render_provenance(state.get("events", []))
    _render_human_actions(packet, state)


def _render_queue(cases: pd.DataFrame) -> None:
    st.subheader("Queue overview")
    eval_mask = cases["is_eval_case"].str.lower().eq("true")
    first_row = st.columns(2)
    first_row[0].metric("Total cases", len(cases))
    first_row[1].metric("Evaluation cases", int(eval_mask.sum()))

    st.caption("Cases by type")
    counts = cases["case_type"].value_counts().sort_index()
    for start in range(0, len(counts), 4):
        row = st.columns(4)
        for column, (case_type, count) in zip(row, counts.iloc[start:start + 4].items()):
            column.metric(case_type.replace("_", " "), int(count))

    filter_text = st.text_input("Filter by case ID", placeholder="e.g. PA-0007")
    queue = cases.loc[
        cases["case_id"].str.contains(filter_text.strip(), case=False, na=False)
    ].copy()
    queue["is_eval_case"] = queue["is_eval_case"].str.lower().eq("true")
    columns = [
        "security_flag", "case_id", "patient_alias", "procedure_name",
        "request_date", "case_type", "is_eval_case",
    ]
    queue["security_flag"] = queue["case_type"].map(
        lambda value: "SECURITY" if str(value).upper() == "PROMPT_INJECTION" else ""
    )
    queue["_security_priority"] = queue["security_flag"].eq("SECURITY")
    queue = queue.sort_values(
        "_security_priority", ascending=False, kind="mergesort"
    ).drop(columns=["_security_priority"])
    st.caption(
        "Security cases are pinned to the top and are visible in full to ADMIN only."
    )

    def _style_security_flag(row: pd.Series) -> list[str]:
        return [
            (
                "background-color: #fee2e2; color: #991b1b; "
                "font-weight: 700"
            )
            if column == "security_flag" and row["security_flag"] == "SECURITY"
            else ""
            for column in row.index
        ]

    styled = queue[columns].style.apply(_style_security_flag, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _analyst_is_security(record: dict[str, Any]) -> bool:
    return "SECURITY" in record.get("flags", []) or str(
        record.get("case_type", "")
    ).strip().upper() == "PROMPT_INJECTION"


def _analyst_result_from_state(
    packet: CasePacket, state: dict[str, Any]
) -> dict[str, Any]:
    """Create the same compact shape as the CLI batch export."""

    assessment = state.get("assessment")
    policy = policy_by_code.get(packet.procedure_code)
    requirement_by_key = {
        requirement.key: requirement
        for requirement in (policy.requirements if policy else [])
    }
    missing_items: list[dict[str, Any]] = []
    if assessment is not None:
        for item in assessment.missing_items:
            key = str(_value(item.requirement))
            requirement = requirement_by_key.get(key)
            missing_items.append(
                {
                    "requirement": key,
                    "label": requirement.label if requirement else key,
                    "reason": item.reason,
                    "evidence_path": item.evidence_path,
                    "evidence_value": item.evidence_value,
                }
            )
    questions = [str(question) for question in state.get("follow_up_questions", [])]
    if not questions:
        questions = [f"Provide {item['label']}" for item in missing_items]
    status = str(_value(state.get("status")) or "ERROR")
    conflicts = [
        str(conflict) for conflict in state.get("conflicts", [])
    ]
    if not conflicts and any(
        event.get("type") == "conflicting_evidence"
        for event in state.get("events", [])
    ):
        conflicts = ["Conflicting evidence requires human review."]
    return {
        "case_id": packet.case_id,
        "case_type": _value(packet.case_type),
        "submission_attempt": packet.submission_attempt,
        "patient_alias": packet.patient_alias or "",
        "procedure_name": packet.procedure_name or "",
        "status": status,
        "route": str(_value(state.get("route")) or "UNROUTED"),
        "confidence": float(state.get("confidence") or 0.0),
        "missing_items": missing_items,
        "conflicts": conflicts,
        "follow_up_questions": questions,
        "flags": ["SECURITY"] if _analyst_is_security({
            "case_type": packet.case_type.value,
        }) else [],
        "needs_attention": status in {"HUMAN_REVIEW", "ERROR"},
    }


def _analyst_error_result(row: dict[str, Any]) -> dict[str, Any]:
    case_type = str(row.get("case_type") or "")
    return {
        "case_id": str(row.get("case_id") or ""),
        "case_type": case_type,
        "patient_alias": str(row.get("patient_alias") or ""),
        "procedure_name": str(row.get("procedure_name") or ""),
        "status": "ERROR",
        "route": "UNROUTED",
        "confidence": 0.0,
        "missing_items": [],
        "conflicts": [],
        "follow_up_questions": [],
        "flags": ["SECURITY"] if case_type == "PROMPT_INJECTION" else [],
        "needs_attention": True,
    }


def _compute_batch_assessment(cases: pd.DataFrame) -> dict[str, Any]:
    """Build the static intake cache when the precomputed file is absent."""

    graph = build_graph()
    batch_cases: list[dict[str, Any]] = []
    for _, row in cases.iterrows():
        raw_row = row.to_dict()
        try:
            packet, issues = packet_from_row(raw_row)
            state = run_packet(packet, issues, graph=graph)
            batch_cases.append(_analyst_result_from_state(packet, state))
        except Exception:
            batch_cases.append(_analyst_error_result(raw_row))
    document = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "baseline",
        "workflow_version": WORKFLOW_VERSION,
        "prompt_version": PROMPT_VERSION,
        "policy_version": POLICY_VERSION,
        "cases": batch_cases,
    }
    BATCH_PATH.parent.mkdir(parents=True, exist_ok=True)
    BATCH_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return document


def _load_batch_assessment(cases: pd.DataFrame) -> dict[str, Any]:
    try:
        document = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
        if isinstance(document, dict) and isinstance(document.get("cases"), list):
            return document
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    with st.spinner("Preparing today's intake assessments…"):
        return _compute_batch_assessment(cases)


def _analyst_decision(record: dict[str, Any]) -> str | None:
    return st.session_state.get("reviewed", {}).get(str(record.get("case_id")))


def _analyst_status_display(record: dict[str, Any]) -> tuple[str, str]:
    decision = _analyst_decision(record)
    if _analyst_is_security(record):
        return "SECURITY", "red"
    if decision == "approved":
        return "APPROVED", "green"
    if decision == "rejected":
        return "REJECTED", "red"
    if decision == "escalated":
        return "ESCALATED", "red"
    if _analyst_is_awaiting(record):
        return "AWAITING PROVIDER", "neutral"
    if record.get("needs_attention"):
        return "NEEDS REVIEW", "red"
    if _analyst_needs_info(record):
        return "MORE INFO NEEDED", "yellow"
    return "AI APPROVED", "yellow"


def _analyst_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    priority = 0 if _analyst_is_security(record) else (
        1 if record.get("needs_attention") else (
            2 if _analyst_needs_info(record) else (
                3 if not _analyst_is_awaiting(record) else 4
            )
        )
    )
    return priority, str(record.get("case_id", ""))


def _analyst_needs_attention_count(records: list[dict[str, Any]]) -> int:
    return sum(
        1
        for record in records
        if (
            record.get("needs_attention")
            or _analyst_decision(record) in {"rejected", "escalated"}
        )
        and _analyst_decision(record) != "approved"
    )


def _render_stat_card(column: Any, label: str, value: int, tone: str) -> None:
    column.markdown(
        f"""
        <div class="stat-card stat-{html.escape(tone)}">
          <div class="stat-label">{html.escape(label)}</div>
          <div class="stat-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_analyst_table(records: list[dict[str, Any]]) -> None:
    st.markdown(
        f'<div class="section-bar">Today\'s cases <span style="font-weight:400;">· '
        f"{len(records)} shown</span></div>",
        unsafe_allow_html=True,
    )
    if not records:
        st.info("No cases match the current filters.")
        return

    rows_html: list[str] = []
    for record in records:
        status_label, tone = _analyst_status_display(record)
        decision = _analyst_decision(record)
        try:
            confidence = f"{float(record.get('confidence') or 0.0):.1%}"
        except (TypeError, ValueError):
            confidence = "n/a"
        reviewed = '<span class="review-check">✓</span>' if decision else "—"
        rows_html.append(
            "<tr>"
            f"<td><strong>{html.escape(str(record.get('case_id', '')))}</strong></td>"
            f"<td>{html.escape(str(record.get('patient_alias', '')))}</td>"
            f"<td>{html.escape(str(record.get('procedure_name', '')))}</td>"
            f"<td>{_status_pill(status_label, tone)}</td>"
            f"<td>{html.escape(str(record.get('route', 'UNROUTED')).replace('_', ' '))}</td>"
            f"<td>{confidence}</td>"
            f"<td>{reviewed}</td>"
            "</tr>"
        )
    st.markdown(
        """
        <div class="analyst-table-wrap">
          <table class="analyst-table">
            <thead><tr>
              <th>Case ID</th><th>Patient alias</th><th>Procedure</th>
              <th>Status</th><th>Route</th><th>Confidence</th><th>Reviewed</th>
            </tr></thead>
            <tbody>
        """ + "".join(rows_html) + """
            </tbody>
          </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _analyst_filtered_records(
    records: list[dict[str, Any]], filter_name: str, search: str
) -> list[dict[str, Any]]:
    search_value = search.strip().lower()

    def matches(record: dict[str, Any]) -> bool:
        if search_value and search_value not in str(record.get("case_id", "")).lower():
            return False
        decision = _analyst_decision(record)
        security = _analyst_is_security(record)
        if filter_name == "Needs attention":
            return (
                (
                    bool(record.get("needs_attention"))
                    or _analyst_needs_info(record)
                    or decision in {"rejected", "escalated"}
                )
                and decision != "approved"
                and not _analyst_is_awaiting(record)
            )
        if filter_name == "AI approved":
            return (
                not record.get("needs_attention")
                and not _analyst_needs_info(record)
                and not _analyst_is_awaiting(record)
                and decision is None
            )
        if filter_name == "Approved":
            return decision == "approved"
        if filter_name == "Security":
            return security
        if filter_name == "Awaiting provider":
            return _analyst_is_awaiting(record)
        return True

    return sorted([record for record in records if matches(record)], key=_analyst_sort_key)


def _render_analyst_attention(
    record: dict[str, Any], policy: PolicyDefinition | None
) -> None:
    requirement_by_key = {
        requirement.key: requirement
        for requirement in (policy.requirements if policy else [])
    }
    blocks: list[str] = []
    for item in record.get("missing_items", []):
        key = str(item.get("requirement", ""))
        requirement = requirement_by_key.get(key)
        label = str(item.get("label") or (requirement.label if requirement else key))
        path = str(item.get("evidence_path") or key)
        value = _text_value(item.get("evidence_value"))
        counterfactual = _counterfactual(requirement) if requirement else f"Provide {label}"
        blocks.append(
            f"<li><strong>{html.escape(label)}</strong>: "
            f"{html.escape(str(item.get('reason') or 'Requirement needs review.'))}"
            f"<br><span>Evidence: <code>{html.escape(path)}</code> = "
            f"<code>{html.escape(value)}</code></span>"
            f"<br><em>Counterfactual: {html.escape(counterfactual)}</em></li>"
        )
    for conflict in record.get("conflicts", []):
        blocks.append(f"<li><strong>Conflict:</strong> {html.escape(str(conflict))}</li>")
    questions = record.get("follow_up_questions", [])
    question_html = "".join(
        f"<li>{html.escape(str(question))}</li>" for question in questions
    )
    if question_html:
        blocks.append(f"<li><strong>Draft follow-up questions</strong><ul>{question_html}</ul></li>")
    if not blocks:
        blocks.append("<li>Review the workflow exception and determine the next action.</li>")
    st.markdown(
        '<div class="attention-box"><strong>What to check</strong>'
        f'<ul>{"".join(blocks)}</ul></div>',
        unsafe_allow_html=True,
    )


def _modified_assessment(
    record: dict[str, Any], packet: CasePacket, policy: PolicyDefinition | None,
    key_suffix: str,
) -> list[dict[str, Any]]:
    if policy is None:
        return list(record.get("missing_items", []))
    original = {
        str(item.get("requirement")): item
        for item in record.get("missing_items", [])
    }
    missing: list[dict[str, Any]] = []
    with st.expander("Adjust the assessment"):
        st.caption("Uncheck a policy requirement to treat it as missing for this review.")
        for requirement in policy.requirements:
            checked = st.checkbox(
                requirement.label,
                value=requirement.key not in original,
                key=f"assessment-{key_suffix}-{requirement.key}",
            )
            if not checked:
                item = dict(original.get(requirement.key, {}))
                if not item:
                    path, evidence = _evidence_for_requirement(packet, requirement)
                    item = {
                        "requirement": requirement.key,
                        "label": requirement.label,
                        "reason": f"Analyst marked {requirement.label} as missing.",
                        "evidence_path": path,
                        "evidence_value": evidence,
                    }
                item.setdefault("label", requirement.label)
                missing.append(item)
    return missing


def _analyst_followups(
    record: dict[str, Any], missing_items: list[dict[str, Any]]
) -> list[str]:
    original_keys = {
        str(item.get("requirement")) for item in record.get("missing_items", [])
    }
    edited_keys = {str(item.get("requirement")) for item in missing_items}
    questions = [str(question) for question in record.get("follow_up_questions", [])]
    if questions and original_keys == edited_keys:
        return questions  # surface the AI-drafted questions (assessment untouched)
    return [
        f"Provide {item.get('label') or item.get('requirement')}"
        for item in missing_items
    ]


def _record_analyst_decision(
    packet: CasePacket,
    record: dict[str, Any],
    decision: str,
    reason: str,
    analyst_note: str | None,
) -> None:
    case_id = packet.case_id
    reviewed_decision = {
        "approve": "approved",
        "reject": "rejected",
        "escalate": "escalated",
    }.get(decision, decision)
    audit.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "event": "human_decision",
            "details": {
                "decision": decision,
                "reason": reason,
                "analyst_note": analyst_note,
                "system_recommendation": {
                    "status": str(record.get("status") or "ERROR"),
                    "route": str(record.get("route") or "UNROUTED"),
                    "confidence": float(record.get("confidence") or 0.0),
                },
            },
        }
    )
    st.session_state.setdefault("reviewed", {})[case_id] = reviewed_decision
    st.session_state.setdefault("review_reasons", {})[case_id] = reason
    st.session_state.setdefault("analyst_notes", {})[case_id] = analyst_note


def _render_full_case(packet: CasePacket, policy: PolicyDefinition | None) -> None:
    """Show the complete case packet to the analyst before any decision is offered."""
    st.subheader("Case packet")
    facts = [
        ("Patient alias", _text_value(packet.patient_alias)),
        ("Diagnosis code", _text_value(packet.diagnosis_code)),
        ("Symptoms", _text_value(packet.symptoms)),
        ("Symptom duration (weeks)", _text_value(packet.symptom_duration_weeks)),
        ("Conservative treatment", _text_value(packet.conservative_treatment)),
        ("Treatment duration (weeks)", _text_value(packet.treatment_duration_weeks)),
        ("Clinical note date", _text_value(packet.clinical_note_date)),
        ("Ordering provider", _text_value(packet.ordering_provider)),
        ("Provider identifier", _text_value(packet.provider_identifier)),
        ("Requested location", _text_value(packet.requested_location)),
        ("Requested units", _text_value(packet.requested_units)),
        ("Submission attempt", _text_value(packet.submission_attempt)),
    ]
    columns = st.columns(2)
    for index, (label, value) in enumerate(facts):
        with columns[index % 2]:
            st.markdown(f"**{label}**  \n{html.escape(value)}")

    st.markdown("**Clinical narrative**")
    note = packet.clinical_note
    if note and str(note).strip():
        st.markdown(
            '<div class="case-note">' + html.escape(str(note)) + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.caption("No clinical narrative in this packet.")

    if policy is not None:
        st.markdown(
            f"**Applied policy** — {policy.procedure_name} ({policy.procedure})"
        )
        for requirement in policy.requirements:
            rules = []
            if requirement.minimum_weeks is not None:
                rules.append(
                    f"≥ {_pretty_number(requirement.minimum_weeks)} weeks documented"
                )
            if requirement.max_age_days is not None:
                rules.append(f"note ≤ {requirement.max_age_days} days old")
            rule_text = " · ".join(rules) if rules else "required"
            st.markdown(f"- **{requirement.label}** — {rule_text}")


def _analyst_needs_info(record: dict[str, Any]) -> bool:
    return str(record.get("status") or "").upper() == "NEEDS_INFORMATION"


def _analyst_is_awaiting(record: dict[str, Any]) -> bool:
    case_id = str(record.get("case_id", ""))
    sent = st.session_state.get("sent_followups", {}).get(case_id)
    responded = st.session_state.get("provider_responded", {}).get(case_id)
    return bool(sent) and not responded


def _record_followup_sent(
    packet: CasePacket,
    record: dict[str, Any],
    questions: list[str],
    note: str | None,
) -> None:
    """Audit the outbound follow-up and park the case in the awaiting state."""
    case_id = packet.case_id
    audit.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "event": "followup_sent",
            "details": {
                "provider": packet.ordering_provider or "",
                "provider_identifier": packet.provider_identifier or "",
                "questions": questions,
                "analyst_note": note,
                "submission_attempt": packet.submission_attempt,
                "system_recommendation": {
                    "status": str(record.get("status") or "ERROR"),
                    "route": str(record.get("route") or "UNROUTED"),
                    "confidence": float(record.get("confidence") or 0.0),
                },
            },
        }
    )
    st.session_state.setdefault("sent_followups", {})[case_id] = {
        "questions": questions,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }


def _render_send_followup(
    packet: CasePacket,
    record: dict[str, Any],
    questions: list[str],
    note: str | None,
    source_index: int,
) -> None:
    st.subheader("Follow-up questions draft")
    default_text = (
        "\n".join(str(question) for question in questions)
        if questions
        else "Please provide the missing documentation for this request."
    )
    edited = st.text_area(
        "Review and edit before sending to the provider",
        value=default_text,
        height=140,
        key=f"fu-draft-{source_index}",
    )
    provider = packet.ordering_provider or "the ordering provider"
    if st.button(
        "Send to provider",
        type="primary",
        key=f"fu-send-{source_index}",
        use_container_width=True,
    ):
        payload = [line.strip() for line in edited.splitlines() if line.strip()]
        if not payload:
            st.error("Add at least one follow-up question before sending.")
        else:
            _record_followup_sent(packet, record, payload, note)
            st.rerun()


def _sample_response_value(key: str) -> str | None:
    """Sample evidence a provider might return for a missing requirement (demo)."""
    samples = {
        "diagnosis_code": "M54.5",
        "symptoms": (
            "Persistent lower back pain radiating to the left leg, worse with "
            "standing and walking."
        ),
        "symptom_duration_weeks": "12",
        "conservative_treatment": (
            "Patient completed 8 weeks of structured physical therapy and an "
            "NSAID trial with partial relief."
        ),
        "clinical_note": (
            "Follow-up note: pain persists despite conservative management; "
            "imaging requested to evaluate suspected radiculopathy."
        ),
        "clinical_note_date": datetime.now(timezone.utc).date().isoformat(),
        "requested_location": "Outpatient radiology center",
        "requested_units": "1",
        "ordering_provider": "Dr. Rivera",
        "provider_identifier": "NPI-88231",
    }
    return samples.get(key)


def _upsert_batch_record(new_record: dict[str, Any]) -> None:
    """Replace one case's assessment in the precomputed batch file."""
    try:
        document = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        return
    case_id = str(new_record.get("case_id", ""))
    attempt = new_record.get("submission_attempt")
    replaced = False
    for index, existing in enumerate(document["cases"]):
        if not isinstance(existing, dict) or str(existing.get("case_id", "")) != case_id:
            continue
        if (
            attempt is not None
            and existing.get("submission_attempt") is not None
            and existing.get("submission_attempt") != attempt
        ):
            continue  # duplicate submissions share a case_id; match the attempt too
        document["cases"][index] = new_record
        replaced = True
        break
    if not replaced:
        document["cases"].append(new_record)
    BATCH_PATH.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _evidence_for_key(
    key: str, requirement_by_key: dict[str, PolicyRequirement]
) -> dict[str, Any]:
    """Sample evidence for one requirement key (empty when no sample exists)."""
    value = _sample_response_value(key)
    if value is None:
        return {}
    out: dict[str, Any] = {key: value}
    requirement = requirement_by_key.get(key)
    if (
        key == "conservative_treatment"
        and requirement is not None
        and requirement.minimum_weeks is not None
    ):
        out["treatment_duration_weeks"] = requirement.minimum_weeks + 2.0
    if key == "clinical_note":
        out["clinical_note_date"] = datetime.now(timezone.utc).date().isoformat()
    return out


def _simulate_provider_response(
    packet: CasePacket, record: dict[str, Any], row: dict[str, Any]
) -> None:
    """Simulate the provider's reply: inject evidence, re-assess as attempt 2."""
    case_id = packet.case_id
    policy = policy_by_code.get(packet.procedure_code)
    requirement_by_key = {
        requirement.key: requirement
        for requirement in (policy.requirements if policy else [])
    }
    graph = build_graph()
    updated_row = dict(row)  # same submission, supplemented — not a new attempt
    injected: dict[str, Any] = {}
    for round_index in range(3):
        candidate, _ = packet_from_row(updated_row)
        state = run_packet(candidate, [], graph=graph)
        assessment = state.get("assessment")
        remaining = assessment.missing_items if assessment is not None else []
        if not remaining:
            break
        items = (
            record.get("missing_items", [])
            if round_index == 0
            else [{"requirement": item.requirement} for item in remaining]
        )
        more = {}
        for item in items:
            more.update(
                _evidence_for_key(str(item.get("requirement", "")), requirement_by_key)
            )
        if not more:
            break
        updated_row.update({key: str(value) for key, value in more.items()})
        injected.update(more)
    new_packet, issues = packet_from_row(updated_row)
    state = run_packet(new_packet, issues, graph=graph)
    new_record = _analyst_result_from_state(new_packet, state)
    _upsert_batch_record(new_record)
    audit.append(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "case_id": case_id,
            "event": "provider_response_simulated",
            "details": {
                "injected_fields": sorted(injected),
                "submission_attempt": new_packet.submission_attempt,
                "new_status": str(new_record.get("status")),
                "new_route": str(new_record.get("route")),
                "system_recommendation": {
                    "status": str(record.get("status") or "ERROR"),
                    "route": str(record.get("route") or "UNROUTED"),
                    "confidence": float(record.get("confidence") or 0.0),
                },
            },
        }
    )
    st.session_state.setdefault("provider_responded", {})[case_id] = True


def _render_awaiting_box(
    packet: CasePacket, record: dict[str, Any], row: dict[str, Any], source_index: int
) -> None:
    sent = st.session_state.get("sent_followups", {}).get(packet.case_id, {})
    sent_at = str(sent.get("sent_at", ""))[:16].replace("T", " ")
    provider = packet.ordering_provider or "the ordering provider"
    st.markdown(
        '<div class="awaiting-box"><strong>Follow-up sent — awaiting provider '
        f"response.</strong> Sent {html.escape(sent_at)} UTC to "
        f"{html.escape(provider)}.</div>",
        unsafe_allow_html=True,
    )
    for question in sent.get("questions", []):
        st.markdown(f"- {html.escape(str(question))}")
    st.caption(
        "Demo: in production the response arrives via intake as a new "
        "submission and the workflow re-runs automatically."
    )
    if st.button(
        "Simulate provider response (demo)",
        key=f"fu-respond-{source_index}",
        use_container_width=True,
    ):
        _simulate_provider_response(packet, record, row)
        st.rerun()


def _render_analyst_case(
    cases: pd.DataFrame, record: dict[str, Any], source_index: int
) -> None:
    case_id = str(record.get("case_id", ""))
    match = cases.loc[cases["case_id"] == case_id]
    if match.empty:
        st.error(f"Case {case_id} was not found in the intake data.")
        return
    attempt = int(record.get("submission_attempt") or 1)
    by_attempt = match.loc[match["submission_attempt"].astype(int) == attempt]
    if not by_attempt.empty:
        match = by_attempt
    selected_row = match.iloc[0]
    packet, issues = packet_from_row(selected_row.to_dict())
    policy = policy_by_code.get(packet.procedure_code)
    decision = _analyst_decision(record)
    status_label, tone = _analyst_status_display(record)
    reason = st.session_state.get("review_reasons", {}).get(case_id, "")
    status_detail = f"Decision reason: {reason}" if not _analyst_is_security(record) and reason and decision in {
        "rejected", "escalated"
    } else None
    _render_status(
        {
            "status": record.get("status", "ERROR"),
            "route": record.get("route", "UNROUTED"),
            "confidence": record.get("confidence", 0.0),
        },
        display_status=status_label,
        tone=tone,
        detail=status_detail,
    )

    if _analyst_is_security(record):
        st.markdown(
            '<div class="security-banner">Security case — packet content restricted. '
            "Escalated to ADMIN.</div>",
            unsafe_allow_html=True,
        )
        if st.button(
            "Escalate to ADMIN",
            key=f"security-escalate-{source_index}",
            use_container_width=False,
            disabled=decision == "escalated",
        ):
            _record_analyst_decision(
                packet, record, "escalate", "PROMPT_INJECTION", ""
            )
            st.rerun()
        return

    attempt = (
        f" · Attempt {packet.submission_attempt}"
        if (packet.submission_attempt or 1) > 1
        else ""
    )
    st.caption(
        f"{packet.patient_alias or 'Unknown patient'} · "
        f"{packet.procedure_name or packet.procedure_code} · "
        f"Request date: {_text_value(packet.request_date)}{attempt}"
    )
    if issues:
        st.warning("Packet parsing issues: " + "; ".join(issues))
    _render_full_case(packet, policy)
    if _analyst_is_awaiting(record):
        _render_awaiting_box(packet, record, selected_row.to_dict(), source_index)
    elif record.get("needs_attention") or _analyst_needs_info(record):
        _render_analyst_attention(record, policy)
    elif decision is None:
        st.info(
            "AI found no issues. Review and sign off to approve, or edit the "
            "assessment / escalate below."
        )

    note = st.text_area(
        "Analyst note",
        value=st.session_state.get("analyst_notes", {}).get(case_id, ""),
        key=f"analyst-note-{source_index}",
        placeholder="Add context for the audit trail…",
    )
    missing_items = _modified_assessment(record, packet, policy, str(source_index))
    questions = _analyst_followups(record, missing_items)
    if _analyst_needs_info(record) and decision is None and not _analyst_is_awaiting(
        record
    ):
        _render_send_followup(packet, record, questions, note, source_index)
    else:
        st.subheader("Follow-up questions draft")
        if questions:
            for question in questions:
                st.markdown(f"- {question}")
        else:
            st.caption("No follow-up questions needed.")

    if not _analyst_is_awaiting(record):
        st.subheader("Decision")
        decision_reason = st.text_input(
            "Decision reason (required for Reject; optional for Escalate)",
            key=f"decision-reason-{source_index}",
        )
        approve, reject, escalate = st.columns(3)
        with approve:
            approve_clicked = st.button(
                "Approve", type="primary", key=f"analyst-approve-{source_index}",
                use_container_width=True,
            )
        with reject:
            reject_clicked = st.button(
                "Reject", key=f"analyst-reject-{source_index}", use_container_width=True
            )
        with escalate:
            escalate_clicked = st.button(
                "Escalate", key=f"analyst-escalate-{source_index}", use_container_width=True
            )
        if approve_clicked:
            _record_analyst_decision(packet, record, "approve", "", note)
            st.rerun()
        if reject_clicked:
            if not decision_reason.strip():
                st.error("A reason is required to reject a case.")
            else:
                _record_analyst_decision(
                    packet, record, "reject", decision_reason.strip(), note
                )
                st.rerun()
        if escalate_clicked:
            _record_analyst_decision(
                packet, record, "escalate", decision_reason.strip(), note
            )
            st.rerun()


def _render_analyst_progress(records: list[dict[str, Any]]) -> None:
    reviewed = st.session_state.get("reviewed", {})
    case_ids = list(dict.fromkeys(str(record.get("case_id", "")) for record in records))
    reviewed_count = sum(1 for case_id in case_ids if reviewed.get(case_id))
    total = len(case_ids)
    st.progress(reviewed_count / total if total else 1.0)
    st.caption(f"Reviewed {reviewed_count} of {total} today")
    if total and reviewed_count == total:
        st.success("🎉 All cases for today have been reviewed.")


def _render_analyst_today(records: list[dict[str, Any]]) -> None:
    filter_options = [
        "All", "Needs attention", "AI approved", "Approved", "Security",
        "Awaiting provider",
    ]
    if hasattr(st, "pills"):
        selected_filter = st.pills(
            "Filter cases", filter_options, default="All", key="analyst-filter-pills"
        ) or "All"
    else:
        selected_filter = st.segmented_control(
            "Filter cases", filter_options, default="All", key="analyst-filter-pills"
        ) or "All"
    search = st.text_input(
        "Search by case ID", placeholder="e.g. PA-0007", key="analyst-case-search"
    )
    _render_analyst_table(_analyst_filtered_records(records, selected_filter, search))


def _render_analyst_review(
    cases: pd.DataFrame, records: list[dict[str, Any]]
) -> None:
    ordered = sorted(
        [{"record": record, "source_index": index} for index, record in enumerate(records)],
        key=lambda item: _analyst_sort_key(item["record"]),
    )
    if not ordered:
        st.info("No cases are available for review.")
        return
    current = min(
        max(int(st.session_state.get("analyst_review_index", 0)), 0), len(ordered) - 1
    )
    back, counter, next_case = st.columns([1, 2, 1])
    with back:
        if st.button("← Back", disabled=current == 0, use_container_width=True):
            current -= 1
            st.session_state["analyst_review_index"] = current
    with next_case:
        if st.button(
            "Next →", disabled=current == len(ordered) - 1, use_container_width=True
        ):
            current += 1
            st.session_state["analyst_review_index"] = current
    with counter:
        st.markdown(
            f'<div class="review-nav">Case {current + 1} of {len(ordered)}</div>',
            unsafe_allow_html=True,
        )
    current_item = ordered[current]
    _render_analyst_case(
        cases, current_item["record"], current_item["source_index"]
    )
    _render_analyst_progress(records)


def _render_analyst_desk(cases: pd.DataFrame) -> None:
    document = _load_batch_assessment(cases)
    records = [
        {key: value for key, value in record.items() if not key.startswith("_")}
        for record in document.get("cases", [])
        if isinstance(record, dict)
    ]
    st.session_state.setdefault("reviewed", {})
    st.session_state.setdefault("review_reasons", {})
    st.session_state.setdefault("analyst_notes", {})
    st.session_state.setdefault("sent_followups", {})
    st.session_state.setdefault("provider_responded", {})
    st.title("Welcome, John 👋 — here are your cases for today.")
    st.caption("Demo environment · synthetic data")
    st.caption("Cases are assessed automatically on intake.")

    reviewed = st.session_state["reviewed"]
    attention_count = _analyst_needs_attention_count(records)
    ai_approved_count = sum(
        1 for record in records
        if not record.get("needs_attention") and _analyst_decision(record) is None
    )
    approved_count = sum(
        1 for record in records if _analyst_decision(record) == "approved"
    )
    stats = st.columns(4)
    _render_stat_card(stats[0], "Today's cases", len(records), "teal")
    _render_stat_card(stats[1], "Needs attention", attention_count, "red")
    _render_stat_card(stats[2], "AI approved", ai_approved_count, "yellow")
    _render_stat_card(stats[3], "Approved", approved_count, "green")

    intake, review = st.tabs(["Today's cases", "Review cases"])
    with intake:
        _render_analyst_today(records)
    with review:
        _render_analyst_review(cases, records)


def _render_evaluation() -> None:
    records: list[dict[str, Any]] = []
    for path in EVAL_PATH.glob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            metrics = document.get("metrics", {})
            versions = document.get("versions", {})
            records.append(
                {
                    "run_id": document.get("run_id", path.stem),
                    "mode": document.get("mode", ""),
                    "timestamp": document.get("timestamp", ""),
                    "timestamp_parsed": pd.to_datetime(
                        document.get("timestamp", ""), errors="coerce", utc=True
                    ),
                    "prompt_version": versions.get("prompt", ""),
                    "workflow_version": versions.get("workflow", ""),
                    "policy_version": versions.get("policy", ""),
                    "eval_set_version": versions.get("eval_set", ""),
                    "routing_accuracy": metrics.get("routing_accuracy"),
                    "status_accuracy": metrics.get("status_accuracy"),
                    "missing_item_recall": metrics.get(
                        "missing_item_recall", metrics.get("recall")
                    ),
                    "missing_item_precision": metrics.get(
                        "missing_item_precision", metrics.get("precision")
                    ),
                    "missing_item_f1": metrics.get(
                        "missing_item_f1", metrics.get("f1")
                    ),
                    "escalation_recall": metrics.get("escalation_recall"),
                    "unsafe_auto_route_rate": metrics.get("unsafe_auto_route_rate"),
                    "unsupported_recommendation_rate": metrics.get(
                        "unsupported_recommendation_rate"
                    ),
                }
            )
        except (OSError, json.JSONDecodeError, TypeError):
            continue

    st.caption("Synthetic simulation — illustrative values.")
    if not records:
        st.info("No evaluation results found.")
        return

    records.sort(
        key=lambda record: (
            record["timestamp_parsed"]
            if not pd.isna(record["timestamp_parsed"])
            else pd.Timestamp.min.tz_localize("UTC")
        ),
        reverse=True,
    )
    latest = records[0]

    st.subheader("Current run")
    metric_groups = [
        [
            ("Routing accuracy", "routing_accuracy"),
            ("Status accuracy", "status_accuracy"),
            ("Missing-item precision", "missing_item_precision"),
            ("Missing-item recall", "missing_item_recall"),
        ],
        [
            ("Missing-item F1", "missing_item_f1"),
            ("Escalation recall", "escalation_recall"),
            ("Unsafe auto-route rate", "unsafe_auto_route_rate"),
            ("Unsupported recommendation rate", "unsupported_recommendation_rate"),
        ],
    ]
    for metric_group in metric_groups:
        columns = st.columns(4)
        for column, (label, key) in zip(columns, metric_group):
            column.metric(label, _pct(latest.get(key)))
    st.caption(
        f"Current prompt: **{latest['prompt_version']}** · "
        f"workflow {latest['workflow_version']} · "
        f"policy {latest['policy_version']} · "
        f"eval set {latest['eval_set_version']}"
    )

    st.subheader("History")
    history_columns = [
        "run_id",
        "timestamp",
        "mode",
        "prompt_version",
        "routing_accuracy",
        "status_accuracy",
        "missing_item_recall",
        "missing_item_precision",
        "missing_item_f1",
        "escalation_recall",
        "unsafe_auto_route_rate",
        "unsupported_recommendation_rate",
    ]
    history_rows = []
    for record in records:
        row = {column: record.get(column, "") for column in history_columns}
        for column in history_columns[4:]:
            row[column] = _pct(row[column])
        history_rows.append(row)
    history = pd.DataFrame(history_rows, columns=history_columns)
    styled = history.style.apply(
        lambda row: ["font-weight: bold" if row.name == 0 else ""] * len(row),
        axis=1,
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.subheader("Performance drift")
    drift_rows = [
        {
            "timestamp": record["timestamp_parsed"],
            "routing_accuracy": record["routing_accuracy"],
            "status_accuracy": record["status_accuracy"],
            "missing_item_recall": record["missing_item_recall"],
            "escalation_recall": record["escalation_recall"],
            "unsafe_auto_route_rate": record["unsafe_auto_route_rate"],
            "unsupported_recommendation_rate": record[
                "unsupported_recommendation_rate"
            ],
        }
        for record in records
        if not pd.isna(record["timestamp_parsed"])
    ]
    if not drift_rows:
        st.info("Evaluation timestamps could not be parsed for performance drift.")
        return
    drift = pd.DataFrame(drift_rows).set_index("timestamp").sort_index()
    accuracy_columns = [
        "routing_accuracy",
        "status_accuracy",
        "missing_item_recall",
        "escalation_recall",
    ]
    safety_columns = [
        "unsafe_auto_route_rate",
        "unsupported_recommendation_rate",
    ]
    st.line_chart(drift[accuracy_columns])
    st.line_chart(drift[safety_columns])
    if len(drift) == 1:
        st.info("Only one evaluation run is available; drift trends need more runs.")
    st.caption(
        "Performance drift across versioned runs — each point is a full "
        "golden-set evaluation. Synthetic simulation — illustrative values."
    )


def _render_audit() -> None:
    records = list(reversed(audit.read(limit=100)))
    st.caption("Newest events first · sensitive fields are redacted by the audit logger.")
    if not records:
        st.info("No audit events recorded yet.")
        return
    display_records = [
        {
            "ts": record.get("ts", ""),
            "case_id": record.get("case_id", ""),
            "event": record.get("event", ""),
            "details": json.dumps(record.get("details", {}), ensure_ascii=False),
        }
        for record in records
    ]
    st.dataframe(pd.DataFrame(display_records), use_container_width=True, hide_index=True)


def _clear_workflow_state() -> None:
    workflow_prefixes = ("state-", "override_open-", "override-reason-")
    for key in list(st.session_state):
        if key.startswith(workflow_prefixes):
            del st.session_state[key]
    for key in (
        "reviewed", "review_reasons", "analyst_notes", "analyst_review_index",
        "analyst-filter-pills", "analyst-case-search",
    ):
        st.session_state.pop(key, None)


def _render_login() -> None:
    st.title("PA Compass")
    st.write("Evidence-grounded prior-authorization intake workflow")
    st.caption("Demo login — no credentials required.")
    admin, analyst = st.columns(2)
    with admin:
        if st.button("Login as ADMIN", type="primary", use_container_width=True):
            st.session_state["role"] = "admin"
            st.rerun()
    with analyst:
        if st.button("Login as Analyst", use_container_width=True):
            st.session_state["role"] = "analyst"
            st.rerun()


def main() -> None:
    _inject_theme()
    role = st.session_state.get("role")
    _, has_key = _resolved_llm_config()
    with st.sidebar:
        st.markdown(
            '<div class="pa-brand"><div class="pa-brand-name">PA Compass</div>'
            '<div class="pa-brand-caption">Prior-authorization intake</div></div>',
            unsafe_allow_html=True,
        )
        if role in {"admin", "analyst"}:
            st.markdown(f"Role: **{role.upper()}**")
            if st.button("Logout", use_container_width=True):
                _clear_workflow_state()
                st.session_state.pop("role", None)
                st.rerun()
        if role == "admin":
            st.divider()
            mode = st.radio(
                "Workflow mode",
                ["deterministic baseline", "LLM extraction"],
                index=0,
            )
        elif role == "analyst":
            mode = "analyst"
        else:
            st.caption("Role: not selected")
            mode = "deterministic baseline"
        if not has_key and role != "analyst":
            st.warning(
                "No API key found. Set OPENAI_API_KEY in `.env` or the "
                "environment. Deterministic baseline mode still works."
            )

    if role not in {"admin", "analyst"}:
        _render_login()
        return

    cases = load_cases(str(CASE_PATH))
    if role == "analyst":
        _render_analyst_desk(cases)
        return

    tab_labels = ["Intake Queue", "Case Review"]
    tab_labels += ["Evaluation", "Audit Log"]
    tabs = st.tabs(tab_labels)
    intake, review = tabs[:2]
    with intake:
        _render_queue(cases)
    with review:
        _render_case_review(cases, mode)
    with tabs[2]:
        _render_evaluation()
    with tabs[3]:
        _render_audit()


if __name__ == "__main__":
    main()
