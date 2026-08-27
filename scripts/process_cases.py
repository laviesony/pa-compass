#!/usr/bin/env python3
"""Run the PA Compass intake workflow over synthetic cases."""

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pa_compass.audit import AuditLogger
from pa_compass.evaluate import (
    escalation_recall,
    missing_item_metrics,
    routing_accuracy,
    status_accuracy,
    unsupported_recommendation_rate,
    unsafe_auto_route_rate,
)
from pa_compass.llm_client import LLMClient
from pa_compass.models import WorkflowState, packet_from_row
from pa_compass.version import (
    EVAL_DATASET_VERSION,
    POLICY_VERSION,
    PROMPT_VERSION,
    WORKFLOW_VERSION,
)
from pa_compass.workflow import build_graph, run_packet


def _value(value: Any) -> str | None:
    return value.value if hasattr(value, "value") else value


def _assessment_status(state: dict) -> str | None:
    """Final workflow state — the recommendation the workflow ends on."""
    return _value(state["status"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/pa_cases.csv", type=Path)
    parser.add_argument("--only-eval", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable LLM evidence extraction, follow-ups, and explanations.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not save the versioned evaluation result.",
    )
    args = parser.parse_args()

    llm_client = LLMClient() if args.llm else None
    graph = build_graph(llm_client)
    mode = "llm" if args.llm else "baseline"
    audit_logger = AuditLogger()

    with args.csv.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    if args.only_eval:
        rows = [row for row in rows if row.get("is_eval_case") == "true"]
    if args.limit is not None:
        rows = rows[: max(0, args.limit)]

    results: list[dict[str, Any]] = []
    llm_items_total = 0
    dropped_claims = 0
    for row in rows:
        packet, issues = packet_from_row(row)
        state = run_packet(packet, issues, graph=graph)
        events = state.get("events", [])
        llm_items_total += sum(
            int(event.get("count", 0))
            for event in events
            if event.get("type") == "llm_items_evaluated"
        )
        dropped_claims += sum(
            1
            for event in events
            if event.get("type") == "ungrounded_claim_dropped"
        )
        assessment = state.get("assessment")
        predicted_missing = {
            item.requirement for item in assessment.missing_items
        } if assessment is not None else set()
        predicted_route = _value(state["route"])
        predicted_status = _assessment_status(state)
        expected_missing = set(packet.expected_missing_items)
        route_ok = predicted_route == _value(packet.expected_route)
        status_ok = predicted_status == _value(packet.expected_status)
        missing_ok = predicted_missing == expected_missing
        audit_logger.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "case_id": packet.case_id,
                "event": "case_processed",
                "details": {
                    "mode": mode,
                    "route": predicted_route,
                    "status": predicted_status,
                    "confidence": state.get("confidence", 0.0),
                },
            }
        )
        results.append(
            {
                "packet": packet,
                "state": state,
                "is_eval": packet.is_eval_case,
                "predicted_missing": predicted_missing,
                "predicted_route": predicted_route,
                "predicted_status": predicted_status,
                "expected_missing": expected_missing,
                "route_ok": route_ok,
                "status_ok": status_ok,
                "missing_ok": missing_ok,
            }
        )

    eval_results = [result for result in results if result["is_eval"]]
    for result in eval_results:
        if result["route_ok"] and result["status_ok"] and result["missing_ok"]:
            continue
        packet = result["packet"]
        details = []
        if not result["route_ok"]:
            details.append(
                f"route predicted={result['predicted_route']} expected={_value(packet.expected_route)}"
            )
        if not result["status_ok"]:
            details.append(
                f"status predicted={result['predicted_status']} expected={_value(packet.expected_status)}"
            )
        if not result["missing_ok"]:
            details.append(
                f"missing predicted={sorted(result['predicted_missing'])} "
                f"expected={sorted(result['expected_missing'])}"
            )
        print(f"{packet.case_id} {packet.case_type.value}: " + "; ".join(details))

    count = len(eval_results)
    expected_routes = [
        _value(result["packet"].expected_route) for result in eval_results
    ]
    predicted_routes = [result["predicted_route"] for result in eval_results]
    expected_statuses = [
        _value(result["packet"].expected_status) for result in eval_results
    ]
    predicted_statuses = [result["predicted_status"] for result in eval_results]
    expected_human = [
        result["packet"].expected_human_review for result in eval_results
    ]
    missing_metrics = missing_item_metrics(
        [result["expected_missing"] for result in eval_results],
        [result["predicted_missing"] for result in eval_results],
    )
    metrics = {
        "routing_accuracy": routing_accuracy(expected_routes, predicted_routes),
        "status_accuracy": status_accuracy(expected_statuses, predicted_statuses),
        "missing_item_precision": missing_metrics["precision"],
        "missing_item_recall": missing_metrics["recall"],
        "missing_item_f1": missing_metrics["f1"],
        "escalation_recall": escalation_recall(expected_human, predicted_statuses),
        "unsafe_auto_route_rate": unsafe_auto_route_rate(
            expected_human, predicted_statuses
        ),
        "unsupported_recommendation_rate": unsupported_recommendation_rate(
            llm_items_total, dropped_claims
        ),
    }

    mode = (
        "full pipeline (LLM extraction)"
        if args.llm
        else "deterministic baseline (no LLM)"
    )
    print(f"\n{mode}")
    print("metric                         value")
    print(f"cases evaluated               {count}")
    print(f"routing accuracy              {metrics['routing_accuracy']:.2%}" if count else "routing accuracy              n/a")
    print(f"status accuracy               {metrics['status_accuracy']:.2%}" if count else "status accuracy               n/a")
    print(f"missing-item precision        {metrics['missing_item_precision']:.2%}")
    print(f"missing-item recall           {metrics['missing_item_recall']:.2%}")
    print(f"missing-item f1               {metrics['missing_item_f1']:.2%}")
    print(f"escalation recall             {metrics['escalation_recall']:.2%}")
    print(f"unsafe auto-route rate        {metrics['unsafe_auto_route_rate']:.2%}")
    print(
        "unsupported-recommendation rate "
        f"{metrics['unsupported_recommendation_rate']:.2%}"
    )

    if args.only_eval and not args.no_save:
        run_timestamp = datetime.now(timezone.utc)
        run_id = run_timestamp.strftime("run-%Y%m%d-%H%M%S")
        result_document = {
            "run_id": run_id,
            "mode": "llm" if args.llm else "baseline",
            "timestamp": run_timestamp.isoformat(),
            "versions": {
                "workflow": WORKFLOW_VERSION,
                "prompt": PROMPT_VERSION,
                "policy": POLICY_VERSION,
                "model": llm_client.model if llm_client is not None else "none",
                "eval_set": EVAL_DATASET_VERSION,
            },
            "metrics": metrics,
            "cases": [
                {
                    "case_id": result["packet"].case_id,
                    "case_type": result["packet"].case_type.value,
                    "expected_route": _value(result["packet"].expected_route),
                    "predicted_route": result["predicted_route"],
                    "expected_status": _value(result["packet"].expected_status),
                    "predicted_status": result["predicted_status"],
                    "expected_missing": sorted(result["expected_missing"]),
                    "predicted_missing": sorted(result["predicted_missing"]),
                    "expected_human": result["packet"].expected_human_review,
                    "predicted_human": result["predicted_status"]
                    == WorkflowState.HUMAN_REVIEW.value,
                }
                for result in eval_results
            ],
        }
        result_dir = Path("data/eval_results")
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"{run_id}.json"
        with result_path.open("w", encoding="utf-8") as result_file:
            json.dump(result_document, result_file, indent=2)
            result_file.write("\n")
        print(f"saved: {result_path}")


if __name__ == "__main__":
    main()
