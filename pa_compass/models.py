"""Typed domain models for the PA Compass intake contract."""

from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class CaseType(str, Enum):
    COMPLETE = "COMPLETE"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    THRESHOLD_FAILURE = "THRESHOLD_FAILURE"
    STALE_INFORMATION = "STALE_INFORMATION"
    CONTRADICTORY_EVIDENCE = "CONTRADICTORY_EVIDENCE"
    MALFORMED_RECORD = "MALFORMED_RECORD"
    UNKNOWN_PROCEDURE = "UNKNOWN_PROCEDURE"
    DUPLICATE_SUBMISSION = "DUPLICATE_SUBMISSION"
    AMBIGUOUS = "AMBIGUOUS"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    LONG_NARRATIVE = "LONG_NARRATIVE"


class WorkflowState(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    POLICY_MATCHED = "POLICY_MATCHED"
    ASSESSED = "ASSESSED"
    READY = "READY"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    HUMAN_DECISION = "HUMAN_DECISION"
    COMPLETE = "COMPLETE"


class FailureState(str, Enum):
    INVALID_PACKET = "INVALID_PACKET"
    UNSUPPORTED_PROCEDURE = "UNSUPPORTED_PROCEDURE"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    MODEL_FAILURE = "MODEL_FAILURE"
    SCHEMA_FAILURE = "SCHEMA_FAILURE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


class Route(str, Enum):
    INTAKE_READY = "INTAKE_READY"
    PROVIDER_FOLLOWUP = "PROVIDER_FOLLOWUP"
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    ADMINISTRATIVE_REVIEW = "ADMINISTRATIVE_REVIEW"
    HUMAN_TRIAGE = "HUMAN_TRIAGE"
    UNSUPPORTED_PROCEDURE = "UNSUPPORTED_PROCEDURE"


class PolicyRequirement(BaseModel):
    key: str
    label: str
    required: bool = True
    minimum_weeks: float | None = None
    max_age_days: int | None = None


class PolicyDefinition(BaseModel):
    procedure: str
    procedure_name: str
    requirements: list[PolicyRequirement]
    routing: dict[str, str]


class MissingItem(BaseModel):
    requirement: str
    reason: str
    evidence_path: str | None = None
    evidence_value: str | float | int | None = None


class EvaluationResult(BaseModel):
    missing_items: list[MissingItem] = Field(default_factory=list)
    status: WorkflowState
    route: Route
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    case_id: str
    missing_items: list[MissingItem] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: dict[str, str | float | int] = Field(default_factory=dict)
    conflicts: list[str | dict[str, str]] = Field(default_factory=list)


class CasePacket(BaseModel):
    case_id: str
    patient_alias: str | None = None
    procedure_code: str
    procedure_name: str | None = None
    request_date: date | None = None
    diagnosis_code: str | None = None
    symptoms: str | None = None
    symptom_duration_weeks: float | None = None
    conservative_treatment: str | None = None
    treatment_duration_weeks: float | None = None
    clinical_note: str | None = None
    clinical_note_date: date | None = None
    ordering_provider: str | None = None
    provider_identifier: str | None = None
    requested_location: str | None = None
    requested_units: int | None = None
    clinical_note_present: bool = False
    order_present: bool = False
    submission_attempt: int = 1
    received_timestamp: datetime | None = None
    case_type: CaseType
    is_eval_case: bool = False
    expected_status: WorkflowState | None = None
    expected_missing_items: list[str] = Field(default_factory=list)
    expected_route: Route | None = None
    expected_human_review: bool = False


def _text(row: dict[str, Any], field: str) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _required_text(row: dict[str, Any], field: str, issues: list[str]) -> str:
    value = _text(row, field)
    if value is None:
        issues.append(f"{field}: missing value")
        return ""
    return value


def _date_value(row: dict[str, Any], field: str, issues: list[str]) -> date | None:
    value = _text(row, field)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(f"{field}: invalid date '{value}'")
        return None


def _datetime_value(
    row: dict[str, Any], field: str, issues: list[str]
) -> datetime | None:
    value = _text(row, field)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        issues.append(f"{field}: invalid datetime '{value}'")
        return None


def _float_value(row: dict[str, Any], field: str, issues: list[str]) -> float | None:
    value = _text(row, field)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        issues.append(f"{field}: invalid float '{value}'")
        return None


def _int_value(row: dict[str, Any], field: str, issues: list[str]) -> int | None:
    value = _text(row, field)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        issues.append(f"{field}: invalid integer '{value}'")
        return None


def _bool_value(row: dict[str, Any], field: str, issues: list[str], default: bool) -> bool:
    value = _text(row, field)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    issues.append(f"{field}: invalid boolean '{value}'")
    return default


def _enum_value(
    row: dict[str, Any],
    field: str,
    enum_type: type[Enum],
    issues: list[str],
    default: Enum | None = None,
) -> Enum | None:
    value = _text(row, field)
    if value is None:
        if default is not None:
            return default
        issues.append(f"{field}: missing value")
        return None
    try:
        return enum_type(value)
    except ValueError:
        issues.append(f"{field}: invalid value '{value}'")
        return default


def packet_from_row(row: dict[str, Any]) -> tuple[CasePacket, list[str]]:
    """Parse a raw CSV row while retaining conversion issues for validation."""

    issues: list[str] = []
    expected_missing = _text(row, "expected_missing_items")
    missing_items = (
        [item.strip() for item in expected_missing.split(";") if item.strip()]
        if expected_missing
        else []
    )

    case_type = _enum_value(row, "case_type", CaseType, issues, CaseType.MALFORMED_RECORD)
    if case_type is None:
        case_type = CaseType.MALFORMED_RECORD

    packet = CasePacket(
        case_id=_required_text(row, "case_id", issues),
        patient_alias=_text(row, "patient_alias"),
        procedure_code=_required_text(row, "procedure_code", issues),
        procedure_name=_text(row, "procedure_name"),
        request_date=_date_value(row, "request_date", issues),
        diagnosis_code=_text(row, "diagnosis_code"),
        symptoms=_text(row, "symptoms"),
        symptom_duration_weeks=_float_value(row, "symptom_duration_weeks", issues),
        conservative_treatment=_text(row, "conservative_treatment"),
        treatment_duration_weeks=_float_value(row, "treatment_duration_weeks", issues),
        clinical_note=_text(row, "clinical_note"),
        clinical_note_date=_date_value(row, "clinical_note_date", issues),
        ordering_provider=_text(row, "ordering_provider"),
        provider_identifier=_text(row, "provider_identifier"),
        requested_location=_text(row, "requested_location"),
        requested_units=_int_value(row, "requested_units", issues),
        clinical_note_present=_bool_value(row, "clinical_note_present", issues, False),
        order_present=_bool_value(row, "order_present", issues, False),
        submission_attempt=_int_value(row, "submission_attempt", issues) or 1,
        received_timestamp=_datetime_value(row, "received_timestamp", issues),
        case_type=case_type,
        is_eval_case=_bool_value(row, "is_eval_case", issues, False),
        expected_status=_enum_value(row, "expected_status", WorkflowState, issues),
        expected_missing_items=missing_items,
        expected_route=_enum_value(row, "expected_route", Route, issues),
        expected_human_review=_bool_value(row, "expected_human_review", issues, False),
    )
    return packet, issues


def load_policies(path: str | Path = "policies/policies.yaml") -> list[PolicyDefinition]:
    """Load and validate the fictional policy catalog from YAML."""

    with Path(path).open(encoding="utf-8") as policy_file:
        document = yaml.safe_load(policy_file)

    if not isinstance(document, dict) or not isinstance(document.get("policies"), list):
        raise ValueError("Policy YAML must contain a 'policies' list")
    return [PolicyDefinition.model_validate(policy) for policy in document["policies"]]
