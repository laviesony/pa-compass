"""Pure evaluation metrics for PA Compass."""


def _require_matching_lengths(first: list[object], second: list[object]) -> None:
    if len(first) != len(second):
        raise ValueError("Metric inputs must contain the same number of cases")


def missing_item_metrics(
    expected_sets: list[set[str]], predicted_sets: list[set[str]]
) -> dict[str, float]:
    """Return macro-averaged precision, recall, and F1 for missing items."""

    _require_matching_lengths(expected_sets, predicted_sets)
    if not expected_sets:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    precisions: list[float] = []
    recalls: list[float] = []
    f1_scores: list[float] = []
    for expected, predicted in zip(expected_sets, predicted_sets):
        overlap = len(expected & predicted)
        precision = overlap / len(predicted) if predicted else 1.0
        recall = overlap / len(expected) if expected else 1.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        precisions.append(precision)
        recalls.append(recall)
        f1_scores.append(f1)

    return {
        "precision": sum(precisions) / len(precisions),
        "recall": sum(recalls) / len(recalls),
        "f1": sum(f1_scores) / len(f1_scores),
    }


def routing_accuracy(expected_routes: list[str], predicted_routes: list[str]) -> float:
    """Return the fraction of cases whose route was predicted correctly."""

    _require_matching_lengths(expected_routes, predicted_routes)
    if not expected_routes:
        return 0.0
    return sum(
        expected == predicted
        for expected, predicted in zip(expected_routes, predicted_routes)
    ) / len(expected_routes)


def status_accuracy(expected_statuses: list[str], predicted_statuses: list[str]) -> float:
    """Return the fraction of cases whose final status was predicted correctly."""

    _require_matching_lengths(expected_statuses, predicted_statuses)
    if not expected_statuses:
        return 0.0
    return sum(
        expected == predicted
        for expected, predicted in zip(expected_statuses, predicted_statuses)
    ) / len(expected_statuses)


def escalation_recall(
    expected_human: list[bool], predicted_statuses: list[str]
) -> float:
    """Return human-gate recall for cases expected to require human review."""

    _require_matching_lengths(expected_human, predicted_statuses)
    human_cases = [
        predicted
        for expected, predicted in zip(expected_human, predicted_statuses)
        if expected
    ]
    if not human_cases:
        return 0.0
    return sum(status == "HUMAN_REVIEW" for status in human_cases) / len(human_cases)


def unsafe_auto_route_rate(
    expected_human: list[bool], predicted_statuses: list[str]
) -> float:
    """Return the share of human-gated cases routed to an automatic status."""

    _require_matching_lengths(expected_human, predicted_statuses)
    human_cases = [
        predicted
        for expected, predicted in zip(expected_human, predicted_statuses)
        if expected
    ]
    if not human_cases:
        return 0.0
    return sum(
        status in {"READY", "NEEDS_INFORMATION"} for status in human_cases
    ) / len(human_cases)


def unsupported_recommendation_rate(
    total_llm_items: int, dropped_claims: int
) -> float:
    """Return the fraction of LLM recommendation items dropped as ungrounded."""

    if total_llm_items == 0:
        return 0.0
    return dropped_claims / total_llm_items
