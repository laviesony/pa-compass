"""PA Compass operations UI for synthetic prior-authorization intake."""

from datetime import datetime, timezone
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
from pa_compass.workflow import build_graph, run_packet


st.set_page_config(page_title="PA Compass", layout="wide")

ROOT = Path(__file__).resolve().parent
CASE_PATH = ROOT / "data" / "pa_cases.csv"
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


def _resolved_llm_config() -> tuple[str, str, bool]:
    provider = (os.getenv("LLM_PROVIDER") or "openai").lower()
    model = os.getenv("LLM_MODEL") or (
        "deepseek-v4-flash" if provider == "deepseek" else "gpt-4o-mini"
    )
    has_key = any(
        bool(os.getenv(name))
        for name in ("LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")
    )
    return provider, model, has_key


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


def _render_status(state: dict[str, Any]) -> None:
    status = str(_value(state.get("status")) or "UNKNOWN")
    route = str(_value(state.get("route")) or "UNROUTED")
    confidence = float(state.get("confidence") or 0.0)
    colors = {
        "READY": ("#dcfce7", "#166534"),
        "NEEDS_INFORMATION": ("#fef3c7", "#92400e"),
        "HUMAN_REVIEW": ("#fee2e2", "#991b1b"),
    }
    background, foreground = colors.get(status, ("#e5e7eb", "#374151"))
    st.markdown(
        f"""
        <div style="background:{background}; border-left:6px solid {foreground};
                    border-radius:8px; padding:18px 22px; margin:8px 0 20px;">
          <div style="color:{foreground}; font-size:2rem; font-weight:700;">
            {status.replace('_', ' ')}
          </div>
          <div style="color:{foreground}; font-size:1rem; margin-top:4px;">
            Route: <strong>{route.replace('_', ' ')}</strong>
            &nbsp;&nbsp;|&nbsp;&nbsp;
            Confidence: <strong>{confidence:.1%}</strong>
          </div>
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
            "Approve recommendation", key=f"approve-{packet.case_id}",
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
            "Confirm override", key=f"confirm-override-{packet.case_id}"
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
            provider, model, has_key = _resolved_llm_config()
            if mode == "LLM extraction":
                if not has_key:
                    raise ValueError(
                        "No LLM API key found. Set LLM_API_KEY, OPENAI_API_KEY, "
                        "or DEEPSEEK_API_KEY in .env or the environment."
                    )
                graph = build_graph(LLMClient(provider=provider, model=model))
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
        "case_id", "patient_alias", "procedure_name", "request_date",
        "case_type", "is_eval_case",
    ]
    st.dataframe(queue[columns], use_container_width=True, hide_index=True)


def _render_evaluation() -> None:
    records: list[dict[str, Any]] = []
    for path in EVAL_PATH.glob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            metrics = document.get("metrics", {})
            records.append(
                {
                    "run_id": document.get("run_id", path.stem),
                    "mode": document.get("mode", ""),
                    "timestamp": document.get("timestamp", ""),
                    "routing_accuracy": _pct(metrics.get("routing_accuracy")),
                    "status_accuracy": _pct(metrics.get("status_accuracy")),
                    "recall": _pct(metrics.get("missing_item_recall", metrics.get("recall"))),
                    "precision": _pct(metrics.get("missing_item_precision", metrics.get("precision"))),
                    "f1": _pct(metrics.get("missing_item_f1", metrics.get("f1"))),
                    "escalation_recall": _pct(metrics.get("escalation_recall")),
                    "unsafe_auto_route_rate": _pct(metrics.get("unsafe_auto_route_rate")),
                    "unsupported_recommendation_rate": _pct(
                        metrics.get("unsupported_recommendation_rate")
                    ),
                }
            )
        except (OSError, json.JSONDecodeError, TypeError):
            continue

    st.caption("Synthetic simulation — illustrative values.")
    if not records:
        st.info("No evaluation results found.")
        return
    records.sort(key=lambda record: record["timestamp"], reverse=True)
    evaluation = pd.DataFrame(records)
    styled = evaluation.style.apply(
        lambda row: ["font-weight: bold" if row.name == 0 else ""] * len(row),
        axis=1,
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


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


def main() -> None:
    cases = load_cases(str(CASE_PATH))
    provider, model, has_key = _resolved_llm_config()
    with st.sidebar:
        st.title("PA Compass")
        mode = st.radio(
            "Workflow mode",
            ["deterministic baseline", "LLM extraction"],
            index=0,
        )
        st.caption(f"Resolved provider: `{provider}`")
        st.caption(f"Resolved model: `{model}`")
        if not has_key:
            st.warning(
                "No API key found. Set LLM_API_KEY, OPENAI_API_KEY, or "
                "DEEPSEEK_API_KEY in `.env` or the environment. Deterministic "
                "baseline mode still works."
            )

    intake, review, evaluation, audit_tab = st.tabs(
        ["Intake Queue", "Case Review", "Evaluation", "Audit Log"]
    )
    with intake:
        _render_queue(cases)
    with review:
        _render_case_review(cases, mode)
    with evaluation:
        _render_evaluation()
    with audit_tab:
        _render_audit()


if __name__ == "__main__":
    main()
