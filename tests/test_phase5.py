from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from typing import Any

from fastapi.testclient import TestClient

from agent.runner import AgentOutput
from api.main import create_app


class CapturingRunner:
    available = True
    model_name = "phase5-capturing-runner"

    def __init__(self) -> None:
        self.runtime_configs: list[dict[str, Any]] = []

    def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        runtime_config: dict[str, Any] | None = None,
    ) -> AgentOutput:
        self.runtime_configs.append(dict(runtime_config or {}))
        return AgentOutput("已按当前发布配置完成只读回答。", 13, 7)


class Phase5TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.business_path = str(root / "phase5.db")
        self.quality_path = str(root / "phase5-quality.db")
        self.agentops_path = str(root / "phase5-agentops.db")
        self.runner = CapturingRunner()
        self.app = create_app(
            db_path=self.business_path,
            quality_path=self.quality_path,
            agentops_path=self.agentops_path,
            session_secret="phase5-test",
            agent_runner=self.runner,
        )
        self.admin = TestClient(self.app)
        self.demo = TestClient(self.app)
        self.assertEqual(
            self.admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code,
            200,
        )
        self.assertEqual(
            self.demo.post("/api/auth/login", json={"username": "demo", "password": "demo"}).status_code,
            200,
        )

    def tearDown(self) -> None:
        self.admin.close()
        self.demo.close()
        self.temp.cleanup()

    def overview(self) -> dict[str, Any]:
        response = self.admin.get("/api/agentops/overview")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def create_validated(self, label: str = "candidate") -> dict[str, Any]:
        settings = dict(self.overview()["stable"]["settings"])
        settings["model_name"] = f"{settings['model_name']}-candidate"
        created = self.admin.post("/api/agentops/configurations", json={"label": label, "settings": settings})
        self.assertEqual(created.status_code, 201, created.text)
        draft = created.json()["configuration"]
        validated = self.admin.post(
            f"/api/agentops/configurations/{draft['version_id']}/validate",
            json={"expected_revision": draft["revision"]},
        )
        self.assertEqual(validated.status_code, 200, validated.text)
        return validated.json()["configuration"]

    def test_control_plane_bootstraps_immutable_secret_free_stable_configuration(self) -> None:
        self.assertEqual(
            set(self.app.state.services.agentops.store.table_names()),
            {"agent_config_versions", "agent_release_state", "agent_release_audit", "agentops_commands"},
        )
        data = self.overview()
        self.assertEqual(data["release"]["generation"], 1)
        self.assertEqual(data["stable"]["status"], "RELEASED")
        self.assertEqual(
            set(data["stable"]["settings"]),
            {"model_name", "max_retries", "temperature", "history_messages", "prompt_version", "toolset_version", "rule_version", "enabled_tools"},
        )
        connection = sqlite3.connect(self.agentops_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn("DASHSCOPE_API_KEY", dump)
        self.assertNotIn("compatible-mode", dump)

    def test_agentops_is_admin_only(self) -> None:
        self.assertEqual(self.demo.get("/api/agentops/overview").status_code, 403)
        self.assertEqual(self.admin.get("/api/agentops/overview").status_code, 200)

    def test_validate_publish_generation_cas_idempotency_and_rollback(self) -> None:
        initial = self.overview()
        original_stable = initial["release"]["stable_version_id"]
        settings = dict(initial["stable"]["settings"])
        created = self.admin.post("/api/agentops/configurations", json={"label": "draft", "settings": settings})
        draft = created.json()["configuration"]
        premature = self.admin.post("/api/agentops/releases", json={
            "version_id": draft["version_id"], "channel": "CANARY", "canary_percent": 10,
            "expected_generation": 1, "command_id": "phase5:premature",
        })
        self.assertEqual(premature.status_code, 409)
        validated = self.admin.post(
            f"/api/agentops/configurations/{draft['version_id']}/validate",
            json={"expected_revision": 1},
        ).json()["configuration"]
        self.assertEqual(validated["status"], "VALIDATED")
        payload = {
            "version_id": draft["version_id"], "channel": "CANARY", "canary_percent": 25,
            "expected_generation": 1, "command_id": "phase5:publish:canary",
        }
        published = self.admin.post("/api/agentops/releases", json=payload)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["release"]["generation"], 2)
        replay = self.admin.post("/api/agentops/releases", json=payload)
        self.assertTrue(replay.json()["idempotent_replay"])
        conflict = self.admin.post("/api/agentops/releases", json={**payload, "canary_percent": 30})
        self.assertEqual(conflict.status_code, 409)
        stale = self.admin.post("/api/agentops/releases", json={
            **payload, "command_id": "phase5:publish:stale", "expected_generation": 1,
        })
        self.assertEqual(stale.status_code, 409)
        rolled = self.admin.post("/api/agentops/rollback", json={
            "target_version_id": original_stable,
            "expected_generation": 2,
            "command_id": "phase5:rollback:stable",
            "reason": "regression",
        })
        self.assertEqual(rolled.status_code, 200, rolled.text)
        self.assertEqual(rolled.json()["release"]["generation"], 3)
        self.assertEqual(rolled.json()["release"]["canary_version_id"], "")

    def test_canary_selection_is_bounded_and_deterministic(self) -> None:
        candidate = self.create_validated()
        release = self.overview()["release"]
        too_large = self.admin.post("/api/agentops/releases", json={
            "version_id": candidate["version_id"], "channel": "CANARY", "canary_percent": 51,
            "expected_generation": release["generation"], "command_id": "phase5:canary:invalid",
        })
        self.assertEqual(too_large.status_code, 400)
        published = self.admin.post("/api/agentops/releases", json={
            "version_id": candidate["version_id"], "channel": "CANARY", "canary_percent": 50,
            "expected_generation": release["generation"], "command_id": "phase5:canary:valid",
        })
        self.assertEqual(published.status_code, 200, published.text)
        selected = [self.app.state.services.agentops.select_configuration(f"cohort-{index}") for index in range(100)]
        self.assertEqual({item["channel"] for item in selected}, {"STABLE", "CANARY"})
        first = self.app.state.services.agentops.select_configuration("repeatable")
        second = self.app.state.services.agentops.select_configuration("repeatable")
        self.assertEqual(first["version_id"], second["version_id"])
        self.assertEqual(first["selection_reason"], second["selection_reason"])

    def test_runtime_selection_is_passed_to_runner_and_persisted_in_trace(self) -> None:
        marker = "PRIVATE-CHAT-MARKER-PHASE5"
        response = self.demo.post("/api/agent/chat/stream", json={
            "chat_id": "chat:phase5-runtime", "message": marker,
        })
        self.assertEqual(response.status_code, 200, response.text)
        events = [json.loads(line) for line in response.text.splitlines() if line]
        complete = events[-1]
        self.assertTrue(self.runner.runtime_configs)
        self.assertEqual(
            self.runner.runtime_configs[-1]["model_name"],
            self.overview()["stable"]["settings"]["model_name"],
        )
        self.assertEqual(complete["trace"]["config_version_id"], complete["runtime"]["config_version_id"])
        self.assertEqual(complete["trace"]["release_channel"], "STABLE")
        detail = self.admin.get(f"/api/agentops/traces/{complete['trace']['trace_id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        connection = sqlite3.connect(self.quality_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        self.assertNotIn(marker, dump)

    def test_metrics_compute_p50_p95_errors_tokens_and_configuration_counts(self) -> None:
        store = self.app.state.services.quality
        for index, (duration, status) in enumerate(((100, "SUCCESS"), (200, "FAILED"), (300, "SUCCESS")), 1):
            trace_id = f"TRC-PHASE5-{index}"
            store.create_run({
                "run_id": f"RUN-PHASE5-{index}", "trace_id": trace_id,
                "actor_ref": "actor", "candidate_ref": "candidate", "chat_id_hash": f"chat-{index}",
                "run_type": "CHAT", "model_name": "test", "prompt_version": "p",
                "toolset_version": "t", "rule_version": "r", "input_chars": 1,
                "config_version_id": "CFG-METRIC", "release_channel": "STABLE", "release_generation": 9,
            })
            store.finish_run(trace_id, {
                "status": status, "output_chars": 1, "input_tokens": index,
                "output_tokens": index * 2, "first_chunk_ms": duration // 2, "total_ms": duration,
            })
        metrics = self.overview()["metrics"]
        self.assertEqual(metrics["run_count"], 3)
        self.assertEqual(metrics["total_ms_p50"], 200)
        self.assertEqual(metrics["total_ms_p95"], 300)
        self.assertEqual(metrics["failed_run_count"], 1)
        self.assertEqual(metrics["input_tokens"], 6)
        self.assertEqual(metrics["output_tokens"], 12)
        self.assertEqual(metrics["by_configuration"]["CFG-METRIC"], 3)

    def test_fixed_evaluation_and_baseline_replay_are_managed_by_api(self) -> None:
        first = self.admin.post("/api/agentops/evaluations/run", json={
            "baseline_name": "phase5-test", "update_baseline": True,
        })
        self.assertEqual(first.status_code, 200, first.text)
        first_run = first.json()["evaluation"]
        self.assertEqual((first_run["passed"], first_run["total"]), (8, 8))
        replay = self.admin.post("/api/agentops/evaluations/replay", json={
            "baseline_name": "phase5-test", "update_baseline": False,
        })
        self.assertEqual(replay.status_code, 200, replay.text)
        replay_run = replay.json()["evaluation"]
        self.assertEqual(replay_run["baseline"]["status"], "MATCH")
        detail = self.admin.get(f"/api/agentops/evaluations/{replay_run['eval_run_id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(len(detail.json()["evaluation"]["results"]), 8)
        self.assertTrue(all(item["passed"] for item in detail.json()["evaluation"]["results"]))

    def test_evaluation_detail_is_not_limited_by_recent_list_pagination(self) -> None:
        rows = []
        for index in range(201):
            timestamp = f"2020-01-01T{index // 60:02d}:{index % 60:02d}:00.000Z"
            rows.append((
                f"EVR-PAGE-{index:03d}", "career-agent-fixed-v1", "pagination",
                "EVAL", "PASSED", 0, 0, "hash", "MATCH", "CFG-PAGE",
                timestamp, timestamp,
            ))
        connection = sqlite3.connect(self.quality_path)
        try:
            connection.executemany(
                """
                INSERT INTO eval_runs (
                    eval_run_id, suite_version, baseline_name, run_mode, status,
                    passed, total, result_hash, baseline_status, config_version_id,
                    started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
        finally:
            connection.close()
        detail = self.app.state.services.quality.get_eval_run("EVR-PAGE-000")
        self.assertEqual(detail["eval_run_id"], "EVR-PAGE-000")
        self.assertEqual(detail["config_version_id"], "CFG-PAGE")

    def test_frontend_exposes_sixth_admin_control_plane_without_deferred_modules(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sidebar = (root / "frontend" / "src" / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
        view = (root / "frontend" / "src" / "views" / "AgentOpsView.vue").read_text(encoding="utf-8")
        self.assertEqual(sidebar.count("{ id: '"), 6)
        self.assertIn("adminOnly: true", sidebar)
        for term in ("generation CAS", "发布灰度", "回滚到此", "固定评测与回放", "Trace 时间线"):
            self.assertIn(term, view)
        self.assertFalse((root / "rag").exists())
        active_source = "\n".join(
            path.read_text(encoding="utf-8", errors="ignore").lower()
            for folder in (root / "core", root / "career", root / "agentops")
            for path in folder.rglob("*.py")
        )
        for deferred in ("create table resume_versions", "create table candidate_skills"):
            self.assertNotIn(deferred, active_source)


if __name__ == "__main__":
    unittest.main()
