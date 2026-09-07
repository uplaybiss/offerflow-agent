from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import time
from typing import Any

from core.ids import new_id
from core.time import utc_now
from quality.store import QualityStore


ALLOWED_BUSINESS_REF_KEYS = {
    "job_id", "job_ids", "application_id", "interview_id", "task_id", "action_id",
    "from_status", "to_status", "resulting_version", "expected_version", "grade",
    "hard_condition_statuses", "reason_code",
}
ALLOWED_METRIC_KEYS = {
    "item_count", "matched_count", "missing_count", "required_total", "preferred_total",
    "input_chars", "output_chars", "input_tokens", "output_tokens",
}


def opaque_ref(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _allow(source: dict[str, Any] | None, allowed: set[str]) -> dict[str, Any]:
    source = source or {}
    result: dict[str, Any] = {}
    for key in allowed:
        if key not in source:
            continue
        value = source[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, list) and all(isinstance(item, (str, int, float, bool)) for item in value):
            result[key] = value[:20]
    return result


@dataclass
class TraceRecorder:
    store: QualityStore
    trace_id: str
    run_id: str
    started_monotonic: float
    sequence: int = 0
    first_chunk_ms: int | None = None
    tool_names: list[str] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        store: QualityStore,
        *,
        actor_username: str,
        candidate_id: str,
        chat_id: str,
        run_type: str,
        model_name: str,
        prompt_version: str,
        toolset_version: str,
        rule_version: str,
        input_chars: int,
        config_version_id: str = "",
        release_channel: str = "UNVERSIONED",
        release_generation: int = 0,
    ) -> "TraceRecorder":
        recorder = cls(store, new_id("TRC"), new_id("RUN"), time.monotonic())
        store.create_run({
            "run_id": recorder.run_id,
            "trace_id": recorder.trace_id,
            "actor_ref": opaque_ref(actor_username),
            "candidate_ref": opaque_ref(candidate_id),
            "chat_id_hash": opaque_ref(chat_id),
            "run_type": run_type,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "toolset_version": toolset_version,
            "rule_version": rule_version,
            "input_chars": input_chars,
            "config_version_id": config_version_id,
            "release_channel": release_channel,
            "release_generation": release_generation,
        })
        return recorder

    def tool_start(self, tool_name: str, risk: str, business_refs: dict[str, Any] | None = None) -> tuple[float, str]:
        self.sequence += 1
        self.tool_names.append(tool_name)
        started_at = utc_now()
        started = time.monotonic()
        event_id = new_id("TEV")
        self.store.append_event({
            "event_id": event_id, "trace_id": self.trace_id, "sequence": self.sequence,
            "event_type": "TOOL_START", "tool_name": tool_name, "risk": risk,
            "status": "RUNNING", "started_at": started_at,
            "business_refs": _allow(business_refs, ALLOWED_BUSINESS_REF_KEYS), "metrics": {},
        })
        return started, started_at

    def tool_end(
        self,
        tool_name: str,
        risk: str,
        started: float,
        started_at: str,
        *,
        status: str,
        reason_code: str = "",
        business_refs: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self.sequence += 1
        self.store.append_event({
            "event_id": new_id("TEV"), "trace_id": self.trace_id, "sequence": self.sequence,
            "event_type": "TOOL_END", "tool_name": tool_name, "risk": risk,
            "status": status, "reason_code": reason_code, "started_at": started_at,
            "ended_at": utc_now(), "duration_ms": round((time.monotonic() - started) * 1000),
            "business_refs": _allow(business_refs, ALLOWED_BUSINESS_REF_KEYS),
            "metrics": _allow(metrics, ALLOWED_METRIC_KEYS),
        })

    def mark_first_chunk(self) -> None:
        if self.first_chunk_ms is None:
            self.first_chunk_ms = round((time.monotonic() - self.started_monotonic) * 1000)

    def finish(self, *, status: str, output_chars: int, input_tokens: int = 0, output_tokens: int = 0) -> dict[str, Any]:
        self.store.finish_run(self.trace_id, {
            "status": status,
            "output_chars": output_chars,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "first_chunk_ms": self.first_chunk_ms,
            "total_ms": round((time.monotonic() - self.started_monotonic) * 1000),
        })
        return self.store.trace_summary(self.trace_id)
