from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from typing import Any, Callable

from core.ids import new_id
from core.time import utc_now
from quality.store import QualityStore


SUITE_VERSION = "career-agent-fixed-v1"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    expected: dict[str, Any]


FIXED_CASES = (
    EvalCase("hard_deadline_reject", "hard_condition", {"grade": "NOT_RECOMMENDED", "failed": "deadline"}),
    EvalCase("hard_graduation_reject", "hard_condition", {"grade": "NOT_RECOMMENDED", "failed": "graduation_year"}),
    EvalCase("required_skill_full_match", "skill_match", {"required_ratio": 1.0}),
    EvalCase("required_skill_gap", "skill_match", {"missing_count": 1}),
    EvalCase("compare_jobs", "read_tool", {"item_count": 2}),
    EvalCase("query_applications", "read_tool", {"minimum_items": 1}),
    EvalCase("confirmed_transition", "write_control", {"persisted": True}),
    EvalCase("unconfirmed_write_blocked", "write_control", {"persisted": False}),
)


SAFE_ACTUAL_KEYS = {
    "grade", "failed", "required_ratio", "missing_count", "item_count",
    "minimum_items", "persisted", "blocked", "status", "tool_name",
}


def _safe_actual(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if key in SAFE_ACTUAL_KEYS and (item is None or isinstance(item, (str, int, float, bool)))
    }


class FixedEvalService:
    def __init__(self, store: QualityStore) -> None:
        self.store = store

    def run(
        self,
        evaluator: Callable[[EvalCase, bool], tuple[bool, dict[str, Any]]],
        *,
        baseline_name: str = "phase4",
        update_baseline: bool = False,
        replay: bool = False,
        config_version_id: str = "",
    ) -> dict[str, Any]:
        started_at = utc_now()
        results: list[dict[str, Any]] = []
        for case in FIXED_CASES:
            started = time.monotonic()
            passed, actual = evaluator(case, True)
            results.append({
                "result_id": new_id("ECR"),
                "case_id": case.case_id,
                "category": case.category,
                "passed": bool(passed),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "expected": case.expected,
                "actual": _safe_actual(actual),
            })
        stable = [
            {"case_id": item["case_id"], "passed": item["passed"], "expected": item["expected"], "actual": item["actual"]}
            for item in results
        ]
        result_hash = hashlib.sha256(
            json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        summary = {
            "suite_version": SUITE_VERSION,
            "passed": sum(1 for item in results if item["passed"]),
            "total": len(results),
            "result_hash": result_hash,
        }
        previous = self.store.get_baseline(baseline_name, SUITE_VERSION)
        if update_baseline or previous is None:
            self.store.upsert_baseline(
                baseline_name=baseline_name,
                suite_version=SUITE_VERSION,
                result_hash=result_hash,
                summary=summary,
            )
            baseline_status = "CREATED" if previous is None else "UPDATED"
        else:
            baseline_status = "MATCH" if previous["result_hash"] == result_hash else "DRIFT"
        eval_run_id = new_id("EVR")
        self.store.save_eval_run(
            eval_run_id=eval_run_id,
            suite_version=SUITE_VERSION,
            baseline_name=baseline_name,
            results=results,
            started_at=started_at,
            run_mode="REPLAY" if replay else "EVAL",
            result_hash=result_hash,
            baseline_status=baseline_status,
            config_version_id=config_version_id,
        )
        return {
            "eval_run_id": eval_run_id,
            "suite_version": SUITE_VERSION,
            "sandbox": True,
            "replay": bool(replay),
            "passed": summary["passed"],
            "total": summary["total"],
            "result_hash": result_hash,
            "baseline": {"name": baseline_name, "status": baseline_status},
            "results": results,
        }

    def replay(
        self,
        evaluator: Callable[[EvalCase, bool], tuple[bool, dict[str, Any]]],
        *,
        baseline_name: str = "phase4",
        config_version_id: str = "",
    ) -> dict[str, Any]:
        return self.run(
            evaluator,
            baseline_name=baseline_name,
            update_baseline=False,
            replay=True,
            config_version_id=config_version_id,
        )
