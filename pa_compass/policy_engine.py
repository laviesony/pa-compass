"""Deterministic policy evaluation and workflow routing."""

from typing import Any

from pa_compass.models import (
    CasePacket,
    EvaluationResult,
    MissingItem,
    PolicyDefinition,
    Route,
    WorkflowState,
)


FIELD_MAP: dict[str, str] = {
    "diagnosis_code": "diagnosis_code",
    "symptoms": "symptoms",
    "symptom_duration_weeks": "symptom_duration_weeks",
    "conservative_treatment": "conservative_treatment",
    "treatment_duration_weeks": "treatment_duration_weeks",
    "clinical_note": "clinical_note",
    "requested_location": "requested_location",
    "ordering_provider": "ordering_provider",
    "requested_units": "requested_units",
}


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _add_missing(items: list[MissingItem], item: MissingItem) -> None:
    if not any(existing.requirement == item.requirement for existing in items):
        items.append(item)


def evaluate_packet(packet: CasePacket, policy: PolicyDefinition) -> list[MissingItem]:
    """Evaluate required fields, numeric thresholds, and note recency."""

    missing_items: list[MissingItem] = []
    for requirement in policy.requirements:
        field = FIELD_MAP.get(requirement.key)
        value = getattr(packet, field, None) if field else None
        if _is_empty(value):
            _add_missing(
                missing_items,
                MissingItem(
                    requirement=requirement.key,
                    reason=(
                        f"Missing {requirement.label} "
                        f"(policy: {policy.procedure})"
                    ),
                    evidence_path=requirement.key,
                    evidence_value=None,
                ),
            )
            continue

        if requirement.minimum_weeks is not None:
            weeks = _number(value)
            # MRI_LUMBAR names the evidence requirement after the treatment
            # history, while its numeric duration is a separate packet field.
            if weeks is None and requirement.key == "conservative_treatment":
                weeks = _number(packet.treatment_duration_weeks)
            if weeks is not None and weeks < requirement.minimum_weeks:
                _add_missing(
                    missing_items,
                    MissingItem(
                        requirement=requirement.key,
                        reason=(
                            f"Only {weeks} weeks documented; policy requires "
                            f"{requirement.minimum_weeks}"
                        ),
                        evidence_path=requirement.key,
                        evidence_value=str(weeks),
                    ),
                )

        if requirement.max_age_days is not None and requirement.key == "clinical_note":
            note_date = packet.clinical_note_date
            if note_date is None:
                _add_missing(
                    missing_items,
                    MissingItem(
                        requirement="clinical_note",
                        reason=(
                            "Clinical note is missing; policy requires "
                            f"≤ {requirement.max_age_days} days"
                        ),
                        evidence_path="clinical_note_date",
                        evidence_value="missing",
                    ),
                )
            elif packet.request_date is not None:
                days = (packet.request_date - note_date).days
                if days > requirement.max_age_days:
                    _add_missing(
                        missing_items,
                        MissingItem(
                            requirement="clinical_note",
                            reason=(
                                f"Clinical note is {days} days old; policy "
                                f"requires ≤ {requirement.max_age_days}"
                            ),
                            evidence_path="clinical_note_date",
                            evidence_value=note_date.isoformat(),
                        ),
                    )

    return missing_items


def compute_confidence(
    packet: CasePacket,
    missing_items: list[MissingItem],
    has_issues: bool,
    policy: PolicyDefinition | None = None,
    evidence_coverage: float = 1.0,
    conflicts: list[str] | None = None,
) -> float:
    """Compute assessment-reliability confidence from observable signals.

    Confidence measures how reliable the assessment is, NOT how complete the
    packet is: missing items are a deterministic finding (they do not lower
    confidence). Formula: start at 1.0; multiply by 0.5 when ``has_issues``
    (malformed record); multiply by 0.5 when ``packet.submission_attempt > 1``
    (duplicate); multiply by 0.5 when ``conflicts`` is non-empty; multiply by
    ``evidence_coverage`` (the caller passes 1.0 when the deterministic
    assessment already found missing items, so only genuinely ambiguous cases —
    where the engine said "complete" but extraction is uncertain — are
    penalized). Clamp to 0..1. A missing policy scores 0 (no assessment
    possible).
    """

    if policy is None:
        return 0.0
    confidence = 1.0
    if has_issues:
        confidence *= 0.5
    if packet.submission_attempt > 1:
        confidence *= 0.5
    if conflicts:
        confidence *= 0.5
    confidence *= max(0.0, min(1.0, evidence_coverage))
    return max(0.0, min(1.0, confidence))


def decide_route(
    packet: CasePacket,
    issues: list[str],
    policy: PolicyDefinition | None,
    missing_items: list[MissingItem],
) -> tuple[WorkflowState, Route]:
    """Apply deterministic routing precedence."""

    if issues:
        return WorkflowState.HUMAN_REVIEW, Route.HUMAN_TRIAGE
    if packet.submission_attempt > 1:
        return WorkflowState.HUMAN_REVIEW, Route.ADMINISTRATIVE_REVIEW
    if policy is None:
        return WorkflowState.HUMAN_REVIEW, Route.UNSUPPORTED_PROCEDURE
    if missing_items:
        return WorkflowState.NEEDS_INFORMATION, Route.PROVIDER_FOLLOWUP
    return WorkflowState.READY, Route.INTAKE_READY


def assess_packet(
    packet: CasePacket,
    issues: list[str],
    policy: PolicyDefinition | None,
) -> EvaluationResult:
    """Run deterministic evaluation, confidence, routing, and explanations."""

    missing_items = evaluate_packet(packet, policy) if policy is not None else []
    confidence = compute_confidence(packet, missing_items, bool(issues), policy)
    status, route = decide_route(packet, issues, policy, missing_items)

    reasons: list[str] = []
    if missing_items:
        reasons.append(f"{len(missing_items)} requirements missing")
    if issues:
        reasons.append("malformed record")
    if packet.submission_attempt > 1:
        reasons.append("duplicate submission")
    if policy is None:
        reasons.append("unsupported procedure")
    if not reasons:
        reasons.append("complete")

    return EvaluationResult(
        missing_items=missing_items,
        status=status,
        route=route,
        confidence=confidence,
        reasons=reasons,
    )
