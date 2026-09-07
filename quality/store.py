from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from core.time import utc_now


QUALITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
    run_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL UNIQUE,
    actor_ref TEXT NOT NULL,
    candidate_ref TEXT NOT NULL,
    chat_id_hash TEXT NOT NULL,
    run_type TEXT NOT NULL CHECK (run_type IN ('CHAT', 'EVAL', 'REPLAY')),
    status TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    toolset_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    config_version_id TEXT NOT NULL DEFAULT '',
    release_channel TEXT NOT NULL DEFAULT 'UNVERSIONED',
    release_generation INTEGER NOT NULL DEFAULT 0,
    input_chars INTEGER NOT NULL DEFAULT 0,
    output_chars INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    first_chunk_ms INTEGER,
    total_ms INTEGER,
    created_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS trace_events (
    event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    tool_name TEXT NOT NULL DEFAULT '',
    risk TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER,
    business_refs_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(trace_id, sequence),
    FOREIGN KEY(trace_id) REFERENCES agent_runs(trace_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_trace_events_trace_sequence
    ON trace_events(trace_id, sequence);

CREATE TABLE IF NOT EXISTS eval_runs (
    eval_run_id TEXT PRIMARY KEY,
    suite_version TEXT NOT NULL,
    baseline_name TEXT NOT NULL,
    run_mode TEXT NOT NULL DEFAULT 'EVAL',
    status TEXT NOT NULL,
    passed INTEGER NOT NULL DEFAULT 0,
    total INTEGER NOT NULL DEFAULT 0,
    result_hash TEXT NOT NULL DEFAULT '',
    baseline_status TEXT NOT NULL DEFAULT '',
    config_version_id TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS eval_case_results (
    result_id TEXT PRIMARY KEY,
    eval_run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
    duration_ms INTEGER NOT NULL,
    expected_json TEXT NOT NULL,
    actual_json TEXT NOT NULL,
    UNIQUE(eval_run_id, case_id),
    FOREIGN KEY(eval_run_id) REFERENCES eval_runs(eval_run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS eval_baselines (
    baseline_name TEXT NOT NULL,
    suite_version TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(baseline_name, suite_version)
);
"""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _percentile(values: list[float], ratio: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * ratio + 0.999999)))
    return round(ordered[index])


def quality_database_path() -> str:
    configured = os.getenv("OFFERFLOW_QUALITY_DB_PATH", "runtime/quality.db")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return str(path.resolve())


class QualityStore:
    def __init__(self, path: str) -> None:
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(QUALITY_SCHEMA)
            migrations = {
                "agent_runs": {
                    "config_version_id": "TEXT NOT NULL DEFAULT ''",
                    "release_channel": "TEXT NOT NULL DEFAULT 'UNVERSIONED'",
                    "release_generation": "INTEGER NOT NULL DEFAULT 0",
                },
                "eval_runs": {
                    "run_mode": "TEXT NOT NULL DEFAULT 'EVAL'",
                    "result_hash": "TEXT NOT NULL DEFAULT ''",
                    "baseline_status": "TEXT NOT NULL DEFAULT ''",
                    "config_version_id": "TEXT NOT NULL DEFAULT ''",
                },
                "eval_case_results": {
                    "category": "TEXT NOT NULL DEFAULT ''",
                },
            }
            for table, columns in migrations.items():
                existing = {
                    str(row["name"])
                    for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for name, definition in columns.items():
                    if name not in existing:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_created ON agent_runs(created_at DESC)"
            )

    def create_run(self, values: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs (
                    run_id, trace_id, actor_ref, candidate_ref, chat_id_hash,
                    run_type, status, model_name, prompt_version, toolset_version,
                    rule_version, config_version_id, release_channel,
                    release_generation, input_chars, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["run_id"], values["trace_id"], values["actor_ref"],
                    values["candidate_ref"], values["chat_id_hash"], values["run_type"],
                    values["model_name"], values["prompt_version"], values["toolset_version"],
                    values["rule_version"], values.get("config_version_id", ""),
                    values.get("release_channel", "UNVERSIONED"),
                    int(values.get("release_generation", 0)),
                    int(values.get("input_chars", 0)), utc_now(),
                ),
            )

    def append_event(self, values: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO trace_events (
                    event_id, trace_id, sequence, event_type, tool_name, risk,
                    status, reason_code, started_at, ended_at, duration_ms,
                    business_refs_json, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["event_id"], values["trace_id"], int(values["sequence"]),
                    values["event_type"], values.get("tool_name", ""), values.get("risk", ""),
                    values["status"], values.get("reason_code", ""), values["started_at"],
                    values.get("ended_at", ""), values.get("duration_ms"),
                    _dump(values.get("business_refs", {})), _dump(values.get("metrics", {})),
                ),
            )

    def finish_run(self, trace_id: str, values: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE agent_runs
                SET status = ?, output_chars = ?, input_tokens = ?, output_tokens = ?,
                    first_chunk_ms = ?, total_ms = ?, finished_at = ?
                WHERE trace_id = ?
                """,
                (
                    values["status"], int(values.get("output_chars", 0)),
                    int(values.get("input_tokens", 0)), int(values.get("output_tokens", 0)),
                    values.get("first_chunk_ms"), values.get("total_ms"), utc_now(), trace_id,
                ),
            )

    def trace_summary(self, trace_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            run = connection.execute("SELECT * FROM agent_runs WHERE trace_id = ?", (trace_id,)).fetchone()
            events = connection.execute(
                "SELECT * FROM trace_events WHERE trace_id = ? ORDER BY sequence", (trace_id,)
            ).fetchall()
        if not run:
            return {}
        return {
            "trace_id": trace_id,
            "run_type": str(run["run_type"]),
            "status": str(run["status"]),
            "model_name": str(run["model_name"]),
            "prompt_version": str(run["prompt_version"]),
            "toolset_version": str(run["toolset_version"]),
            "rule_version": str(run["rule_version"]),
            "config_version_id": str(run["config_version_id"]),
            "release_channel": str(run["release_channel"]),
            "release_generation": int(run["release_generation"]),
            "input_chars": int(run["input_chars"]),
            "output_chars": int(run["output_chars"]),
            "input_tokens": int(run["input_tokens"]),
            "output_tokens": int(run["output_tokens"]),
            "first_chunk_ms": run["first_chunk_ms"],
            "total_ms": run["total_ms"],
            "events": [
                {
                    "sequence": int(row["sequence"]), "event_type": str(row["event_type"]),
                    "tool_name": str(row["tool_name"]), "risk": str(row["risk"]),
                    "status": str(row["status"]), "reason_code": str(row["reason_code"]),
                    "duration_ms": row["duration_ms"],
                    "business_refs": json.loads(str(row["business_refs_json"])),
                    "metrics": json.loads(str(row["metrics_json"])),
                }
                for row in events
            ],
        }

    def save_eval_run(
        self,
        *,
        eval_run_id: str,
        suite_version: str,
        baseline_name: str,
        results: list[dict[str, Any]],
        started_at: str,
        run_mode: str = "EVAL",
        result_hash: str = "",
        baseline_status: str = "",
        config_version_id: str = "",
    ) -> None:
        finished = utc_now()
        passed = sum(1 for item in results if item["passed"])
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO eval_runs (
                    eval_run_id, suite_version, baseline_name, run_mode, status,
                    passed, total, result_hash, baseline_status, config_version_id,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eval_run_id, suite_version, baseline_name, run_mode,
                    "PASSED" if passed == len(results) else "FAILED", passed, len(results),
                    result_hash, baseline_status, config_version_id, started_at, finished,
                ),
            )
            for item in results:
                connection.execute(
                    """
                    INSERT INTO eval_case_results (
                        result_id, eval_run_id, case_id, category, passed,
                        duration_ms, expected_json, actual_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (item["result_id"], eval_run_id, item["case_id"], item.get("category", ""), 1 if item["passed"] else 0,
                     int(item["duration_ms"]), _dump(item["expected"]), _dump(item["actual"])),
                )

    def list_runs(
        self,
        *,
        limit: int = 50,
        status: str = "",
        run_type: str = "",
        config_version_id: str = "",
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("status = ?")
            values.append(status.upper())
        if run_type:
            clauses.append("run_type = ?")
            values.append(run_type.upper())
        if config_version_id:
            clauses.append("config_version_id = ?")
            values.append(config_version_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(max(1, min(int(limit), 200)))
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM agent_runs {where} ORDER BY created_at DESC LIMIT ?", values
            ).fetchall()
        return [
            {
                "run_id": str(row["run_id"]),
                "trace_id": str(row["trace_id"]),
                "run_type": str(row["run_type"]),
                "status": str(row["status"]),
                "model_name": str(row["model_name"]),
                "config_version_id": str(row["config_version_id"]),
                "release_channel": str(row["release_channel"]),
                "release_generation": int(row["release_generation"]),
                "input_tokens": int(row["input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "first_chunk_ms": row["first_chunk_ms"],
                "total_ms": row["total_ms"],
                "created_at": str(row["created_at"]),
                "finished_at": str(row["finished_at"]),
            }
            for row in rows
        ]

    def list_eval_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM eval_runs ORDER BY started_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [
            {
                "eval_run_id": str(row["eval_run_id"]),
                "suite_version": str(row["suite_version"]),
                "baseline_name": str(row["baseline_name"]),
                "run_mode": str(row["run_mode"]),
                "status": str(row["status"]),
                "passed": int(row["passed"]),
                "total": int(row["total"]),
                "result_hash": str(row["result_hash"]),
                "baseline_status": str(row["baseline_status"]),
                "config_version_id": str(row["config_version_id"]),
                "started_at": str(row["started_at"]),
                "finished_at": str(row["finished_at"]),
            }
            for row in rows
        ]

    def get_eval_run(self, eval_run_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            run = connection.execute(
                "SELECT * FROM eval_runs WHERE eval_run_id = ?",
                (eval_run_id,),
            ).fetchone()
            if not run:
                return {}
            rows = connection.execute(
                "SELECT * FROM eval_case_results WHERE eval_run_id = ? ORDER BY case_id",
                (eval_run_id,),
            ).fetchall()
        return {
            "eval_run_id": str(run["eval_run_id"]),
            "suite_version": str(run["suite_version"]),
            "baseline_name": str(run["baseline_name"]),
            "run_mode": str(run["run_mode"]),
            "status": str(run["status"]),
            "passed": int(run["passed"]),
            "total": int(run["total"]),
            "result_hash": str(run["result_hash"]),
            "baseline_status": str(run["baseline_status"]),
            "config_version_id": str(run["config_version_id"]),
            "started_at": str(run["started_at"]),
            "finished_at": str(run["finished_at"]),
            "results": [
                {
                    "result_id": str(row["result_id"]),
                    "case_id": str(row["case_id"]),
                    "category": str(row["category"]),
                    "passed": bool(row["passed"]),
                    "duration_ms": int(row["duration_ms"]),
                    "expected": json.loads(str(row["expected_json"])),
                    "actual": json.loads(str(row["actual_json"])),
                }
                for row in rows
            ],
        }

    def runtime_metrics(self, window_minutes: int = 60) -> dict[str, Any]:
        minutes = max(1, min(int(window_minutes), 24 * 60))
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT status, total_ms, first_chunk_ms, input_tokens, output_tokens,
                       config_version_id, release_channel
                FROM agent_runs
                WHERE created_at >= ? AND finished_at != ''
                ORDER BY created_at
                """,
                (since,),
            ).fetchall()
        total = len(rows)
        failed = sum(1 for row in rows if str(row["status"]) != "SUCCESS")
        total_values = [float(row["total_ms"]) for row in rows if row["total_ms"] is not None]
        first_values = [float(row["first_chunk_ms"]) for row in rows if row["first_chunk_ms"] is not None]
        by_channel: dict[str, int] = {}
        by_configuration: dict[str, int] = {}
        for row in rows:
            channel = str(row["release_channel"] or "UNVERSIONED")
            version = str(row["config_version_id"] or "UNVERSIONED")
            by_channel[channel] = by_channel.get(channel, 0) + 1
            by_configuration[version] = by_configuration.get(version, 0) + 1
        return {
            "window_minutes": minutes,
            "since": since,
            "run_count": total,
            "failed_run_count": failed,
            "error_rate": round(failed / total, 6) if total else 0.0,
            "total_ms_p50": _percentile(total_values, 0.50),
            "total_ms_p95": _percentile(total_values, 0.95),
            "first_chunk_ms_p50": _percentile(first_values, 0.50),
            "first_chunk_ms_p95": _percentile(first_values, 0.95),
            "input_tokens": sum(int(row["input_tokens"] or 0) for row in rows),
            "output_tokens": sum(int(row["output_tokens"] or 0) for row in rows),
            "by_channel": by_channel,
            "by_configuration": by_configuration,
            "cost": None,
            "cost_reason": "未维护带生效时间的模型价格目录，不输出推测成本。",
        }

    def get_baseline(self, baseline_name: str, suite_version: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM eval_baselines WHERE baseline_name = ? AND suite_version = ?",
                (baseline_name, suite_version),
            ).fetchone()
        if not row:
            return None
        return {"result_hash": str(row["result_hash"]), "summary": json.loads(str(row["summary_json"]))}

    def upsert_baseline(self, *, baseline_name: str, suite_version: str, result_hash: str, summary: dict[str, Any]) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO eval_baselines (baseline_name, suite_version, result_hash, summary_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(baseline_name, suite_version) DO UPDATE SET
                    result_hash = excluded.result_hash, summary_json = excluded.summary_json,
                    created_at = excluded.created_at
                """,
                (baseline_name, suite_version, result_hash, _dump(summary), utc_now()),
            )
