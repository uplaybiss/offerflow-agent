from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from typing import Any

from fastapi.testclient import TestClient

from agent.context import AgentRequestContext, bind_agent_context
from agent.runner import AgentOutput, LangChainCareerAgentRunner
from agent.tools import (
    CAREER_TOOL_NAMES,
    confirm_application_change,
    enabled_tools_sha256,
    propose_application_change,
)
from agentops.service import AgentOpsService
from agentops.store import AgentOpsStore
from api.main import create_app
from core.database import Database
from core.errors import ConflictError, NotFoundError
from quality.contract_eval import CONTRACT_CASES, CONTRACT_SUITE_VERSION
from quality.trace import TraceRecorder


def future(days: int, hour: int = 10) -> str:
    value = datetime.now(timezone.utc) + timedelta(days=days)
    return value.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CapturingRunner:
    available = True
    model_name = "final-hardening-capture"

    def __init__(self) -> None:
        self.histories: list[list[dict[str, str]]] = []
        self.runtime_configs: list[dict[str, Any]] = []

    def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        runtime_config: dict[str, Any] | None = None,
    ) -> AgentOutput:
        self.histories.append(list(history))
        self.runtime_configs.append(dict(runtime_config or {}))
        return AgentOutput("合成测试回答")


class FakeGraph:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.messages = list(payload["messages"])
        return {"messages": [type("Message", (), {"content": "ok", "usage_metadata": {}})()]}


class FinalHardeningTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.business_path = str(root / "business.db")
        self.quality_path = str(root / "quality.db")
        self.agentops_path = str(root / "agentops.db")
        self.runner = CapturingRunner()
        self.app = create_app(
            db_path=self.business_path,
            quality_path=self.quality_path,
            agentops_path=self.agentops_path,
            session_secret="final-hardening-test",
            agent_runner=self.runner,
        )
        self.demo = TestClient(self.app)
        self.admin = TestClient(self.app)
        self.assertEqual(self.demo.post("/api/auth/login", json={"username": "demo", "password": "demo"}).status_code, 200)
        self.assertEqual(self.admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code, 200)
        self.candidate = self.app.state.services.candidate.get("demo")
        self.counter = 0

    def tearDown(self) -> None:
        self.demo.close()
        self.admin.close()
        self.temp.cleanup()

    def job(self, company: str | None = None, **changes: Any) -> dict[str, Any]:
        self.counter += 1
        payload: dict[str, Any] = {
            "company_name": company or f"合成公司{self.counter}",
            "title": f"AI 应用工程师{self.counter}",
            "location": "上海",
            "employment_type": "全职",
            "graduation_year": "2027",
            "deadline": "2030-12-31",
            "status": "ACTIVE",
            "required_skills": ["Python"],
            "preferred_skills": [],
            "is_favorite": True,
        }
        payload.update(changes)
        return self.app.state.services.jobs.create(self.candidate["candidate_id"], payload)

    def application(self, job_id: str, *, status: str = "APPLIED") -> dict[str, Any]:
        self.counter += 1
        return self.app.state.services.applications.create(
            self.candidate["candidate_id"], "demo",
            {"job_id": job_id, "status": status, "command_id": f"hardening:create:{self.counter}"},
        )["application"]

    def interview_application(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        job = self.job()
        application = self.application(job["job_id"], status="APPLIED")
        self.counter += 1
        application = self.app.state.services.applications.transition(
            self.candidate["candidate_id"], application["application_id"], "demo",
            {"status": "INTERVIEW", "version": application["version"], "command_id": f"hardening:interview:{self.counter}"},
        )["application"]
        interview = self.app.state.services.interviews.create(
            self.candidate["candidate_id"], application["application_id"],
            {"round_type": "TECHNICAL", "title": "一面", "status": "SCHEDULED", "scheduled_at": future(1)},
        )
        return job, application, interview

    def progression(self, application: dict[str, Any], interview: dict[str, Any], *, task_title: str = "准备二面") -> dict[str, Any]:
        self.counter += 1
        return self.app.state.services.pending_actions.propose_interview_progression(
            candidate_id=self.candidate["candidate_id"], actor_username="demo",
            chat_id=f"chat:progression:{self.counter}", application_id=application["application_id"],
            current_round_id=interview["round_id"], current_round_result="通过",
            next_round_type="TECHNICAL", next_round_title="二面",
            next_round_scheduled_at=future(7), task_title=task_title, task_due_at=future(6),
            expected_application_version=application["version"],
            expected_interview_version=interview["version"],
        )["action"]

    def table_counts(self) -> dict[str, int]:
        tables = ("applications", "application_events", "interview_rounds", "job_search_tasks", "pending_actions")
        connection = sqlite3.connect(self.business_path)
        try:
            return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
        finally:
            connection.close()

    def test_matching_merges_languages_rejects_closed_and_has_no_critical_logic(self) -> None:
        candidate = self.app.state.services.candidate.update("demo", {
            **self.candidate,
            "version": self.candidate["version"],
            "graduation_year": "2027",
            "preferred_cities": ["上海"],
            "preferences": {"languages": []},
            "current_resume_parsed": {"languages": ["英语"]},
            "skills": ["Python"],
        })
        language_job = self.job(source_metadata={"phase2_parsed": {"hard_conditions": {"required_languages": ["English"]}}})
        result = self.app.state.services.matching.match_job(candidate, language_job["job_id"])
        language = next(item for item in result["hard_conditions"] if item["name"] == "languages")
        self.assertEqual(language["status"], "PASS")
        self.assertNotIn("critical_gaps", result)
        self.assertNotIn("critical_required_skills", result)

        chinese_job = self.job(source_metadata={"phase2_parsed": {"hard_conditions": {"required_languages": ["中文"]}}})
        preference_candidate = {
            **candidate,
            "preferences": {"languages": ["English"]},
            "current_resume_parsed": {"languages": []},
        }
        english_job = self.job(source_metadata={"phase2_parsed": {"hard_conditions": {"required_languages": ["英语"]}}})
        preference_match = self.app.state.services.matching.match_job(preference_candidate, english_job["job_id"])
        self.assertEqual(next(item for item in preference_match["hard_conditions"] if item["name"] == "languages")["status"], "PASS")
        missing_candidate = {
            **candidate,
            "preferences": {"languages": []},
            "current_resume_parsed": {"languages": ["Chinese"]},
        }
        missing_match = self.app.state.services.matching.match_job(missing_candidate, language_job["job_id"])
        self.assertEqual(next(item for item in missing_match["hard_conditions"] if item["name"] == "languages")["status"], "FAIL")
        chinese_match = self.app.state.services.matching.match_job(missing_candidate, chinese_job["job_id"])
        self.assertEqual(next(item for item in chinese_match["hard_conditions"] if item["name"] == "languages")["status"], "PASS")

        closed = self.job(status="CLOSED", required_skills=["Python"])
        closed_result = self.app.state.services.matching.match_job(candidate, closed["job_id"])
        self.assertEqual(closed_result["grade"], "NOT_RECOMMENDED")
        availability = next(item for item in closed_result["hard_conditions"] if item["name"] == "job_availability")
        self.assertEqual(availability["status"], "FAIL")

        no_language = self.job()
        unknown = self.app.state.services.matching.match_job(candidate, no_language["job_id"])
        self.assertEqual(next(item for item in unknown["hard_conditions"] if item["name"] == "languages")["status"], "UNKNOWN")

    def test_skill_gap_aggregates_canonical_skill_once(self) -> None:
        candidate = self.app.state.services.candidate.update("demo", {
            **self.candidate,
            "version": self.candidate["version"],
            "graduation_year": "2027",
            "preferred_cities": ["上海"],
            "skills": ["Python"],
        })
        first = self.job(required_skills=["FastAPI", "Python"], preferred_skills=["Django", "Redis"])
        second = self.job(required_skills=["Fast API", "Python"], preferred_skills=["Django"])
        result = self.app.state.services.skill_gaps.analyze(candidate, job_ids=[first["job_id"], second["job_id"]])
        fastapi = [item for item in result["skills"] if item["canonical_skill"] == "fastapi"]
        self.assertEqual(len(fastapi), 1)
        self.assertEqual(fastapi[0]["required_count"], 2)
        self.assertEqual(fastapi[0]["total_jobs"], 2)
        self.assertEqual(set(fastapi[0]["variants"]), {"FastAPI", "Fast API"})
        self.assertEqual(result["frequent_missing_required"][0]["canonical_skill"], "fastapi")
        self.assertTrue(any(item["canonical_skill"] == "python" for item in result["frequent_present"]))
        self.assertTrue(any(item["canonical_skill"] == "django" for item in result["frequent_missing_preferred"]))
        self.assertTrue(any(item["canonical_skill"] == "redis" for item in result["low_frequency_missing"]))

    def test_write_apis_reject_malformed_json_shapes_and_invalid_fields(self) -> None:
        job = self.job()
        application = self.application(job["job_id"])
        interview = self.app.state.services.interviews.create(
            self.candidate["candidate_id"], application["application_id"],
            {"title": "一面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": future(2)},
        )
        task = self.app.state.services.tasks.create(self.candidate["candidate_id"], {
            "title": "准备", "task_type": "GENERAL", "status": "TODO", "priority": "P2", "due_at": future(1),
        })
        cases = (
            (self.demo, "post", "/api/parsing/resume/preview", "[]"),
            (self.demo, "post", "/api/parsing/jd/preview", "null"),
            (self.demo, "post", "/api/agent/chat/stream", '"abc"'),
            (self.demo, "post", f"/api/applications/{application['application_id']}/transitions", "[]"),
            (self.demo, "post", "/api/applications", "123"),
            (self.demo, "post", "/api/jobs", "123"),
            (self.demo, "put", "/api/candidate", "[]"),
            (self.demo, "patch", f"/api/tasks/{task['task_id']}", "null"),
            (self.demo, "patch", f"/api/interviews/{interview['round_id']}", '"abc"'),
            (self.admin, "post", "/api/agentops/configurations", "[]"),
            (self.admin, "post", "/api/agentops/configurations/CFG-UNKNOWN/validate", '"abc"'),
            (self.admin, "post", "/api/agentops/releases", "null"),
            (self.admin, "post", "/api/agentops/rollback", "[]"),
        )
        for client, method, path, content in cases:
            response = client.request(method, path, content=content, headers={"content-type": "application/json"})
            self.assertEqual(response.status_code, 422, (path, response.text))
        self.assertEqual(self.demo.post("/api/parsing/resume/preview", json={}).status_code, 422)
        self.assertEqual(self.demo.post(
            f"/api/applications/{application['application_id']}/transitions",
            json={"status": "INVALID", "version": 1, "command_id": "hardening:invalid"},
        ).status_code, 422)
        self.assertEqual(self.demo.patch(
            f"/api/tasks/{task['task_id']}", json={"version": 1, "title": ["wrong"]},
        ).status_code, 422)

    def test_memory_round_trip_uses_live_references_and_frontend_validates_them(self) -> None:
        job = self.job()
        chat_id = "chat:memory-restore"
        response = self.demo.post("/api/agent/chat/stream", json={
            "chat_id": chat_id,
            "message": "查看这个岗位",
            "current_job_id": job["job_id"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        memory_response = self.demo.get(f"/api/agent/memory/{chat_id}")
        self.assertEqual(memory_response.status_code, 200)
        self.assertEqual(memory_response.json()["memory"]["current_job_id"], job["job_id"])
        self.assertEqual(self.demo.get(f"/api/jobs/{job['job_id']}").status_code, 200)

        self.app.state.services.auth.create_user("alice", "alice", role="user")
        alice = self.app.state.services.candidate.get("alice")
        alice_job = self.app.state.services.jobs.create(alice["candidate_id"], {
            "company_name": "隔离岗位公司", "title": "隔离岗位", "status": "ACTIVE",
            "deadline": "2030-12-31", "required_skills": [], "preferred_skills": [],
        })
        with self.assertRaises(NotFoundError):
            self.app.state.services.memory.remember(
                self.candidate["candidate_id"], "chat:invalid-memory", message="查看岗位",
                current_job_id=alice_job["job_id"],
            )

        frontend = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "CareerAgentView.vue").read_text(encoding="utf-8")
        for term in ("/api/agent/memory/", "/api/jobs", "/api/applications", "/api/interviews", "/api/tasks", "effective_status !== 'ARCHIVED'", "some(item =>"):
            self.assertIn(term, frontend)
        self.assertNotIn("memory.chat", frontend)

    def test_history_window_4_12_20_is_applied_by_langchain_runner(self) -> None:
        history = [{"role": "user" if index % 2 == 0 else "assistant", "content": f"m{index}"} for index in range(20)]
        runner = LangChainCareerAgentRunner()
        runner.available = True
        for limit in (4, 12, 20):
            graph = FakeGraph()
            runner._graph_for = lambda settings, current=graph: current  # type: ignore[method-assign]
            output = runner.run(message="current", history=history, runtime_config={"history_messages": limit})
            self.assertEqual(output.answer, "ok")
            self.assertEqual(len(graph.messages) - 1, limit)
            self.assertEqual(graph.messages[-1]["content"], "current")

    def test_history_20_and_whitelist_summary_are_persisted_in_trace(self) -> None:
        settings = dict(self.app.state.services.agentops.default_settings())
        settings["history_messages"] = 20
        config = self.app.state.services.agentops.create_configuration({"label": "history-20", "settings": settings}, "admin")
        config = self.app.state.services.agentops.validate_configuration(config["version_id"], config["revision"], "admin")
        release = self.app.state.services.agentops.store.release_state()
        self.app.state.services.agentops.publish({
            "version_id": config["version_id"], "channel": "STABLE", "canary_percent": 0,
            "expected_generation": release["generation"], "command_id": "hardening:history:publish",
        }, "admin")
        history = [{"role": "user", "content": f"message-{index}"} for index in range(20)]
        result = self.app.state.services.agent.run(
            candidate=self.candidate, actor_username="demo",
            payload={"chat_id": "chat:history-twenty", "message": "继续", "history": history},
        )
        self.assertEqual(len(self.runner.histories[-1]), 20)
        self.assertEqual(result["runtime"]["history_messages_used"], 20)
        self.assertEqual(result["trace"]["history_messages_used"], 20)
        self.assertEqual(result["trace"]["enabled_tool_count"], len(CAREER_TOOL_NAMES))
        self.assertEqual(result["trace"]["enabled_tools_sha256"], enabled_tools_sha256(list(CAREER_TOOL_NAMES)))

    def test_tool_whitelist_validation_schema_channels_and_confirmation_boundary(self) -> None:
        service = self.app.state.services.agentops
        all_settings = service.default_settings()
        self.assertFalse(service.validate_settings({**all_settings, "enabled_tools": []})["valid"])
        self.assertFalse(service.validate_settings({**all_settings, "enabled_tools": ["unknown_tool"]})["valid"])
        read_only = list(CAREER_TOOL_NAMES[:8])
        runner = LangChainCareerAgentRunner()
        self.assertEqual(runner.tools_for({"enabled_tools": read_only}), read_only)
        self.assertNotIn("propose_application_change", runner.tools_for({"enabled_tools": read_only}))

        draft = service.create_configuration({"label": "read-only-canary", "settings": {**all_settings, "enabled_tools": read_only}}, "admin")
        draft = service.validate_configuration(draft["version_id"], draft["revision"], "admin")
        release = service.store.release_state()
        service.publish({
            "version_id": draft["version_id"], "channel": "CANARY", "canary_percent": 50,
            "expected_generation": release["generation"], "command_id": "hardening:readonly:canary",
        }, "admin")
        state = service.store.release_state()
        stable = service.store.get_configuration(state["stable_version_id"])
        canary = service.store.get_configuration(state["canary_version_id"])
        self.assertEqual(stable["settings"]["enabled_tools"], list(CAREER_TOOL_NAMES))
        self.assertEqual(canary["settings"]["enabled_tools"], read_only)

        canary_chat = next(
            chat_id
            for index in range(1_000)
            for chat_id in (f"chat:readonly-canary-{index}",)
            if service.select_configuration(f"{self.candidate['candidate_id']}:{chat_id}")["channel"] == "CANARY"
        )
        runtime = self.app.state.services.agent.run(
            candidate=self.candidate, actor_username="demo",
            payload={"chat_id": canary_chat, "message": "只读查询"},
        )["runtime"]
        self.assertEqual(runtime["release_channel"], "CANARY")
        self.assertEqual(runtime["config_version_id"], draft["version_id"])
        self.assertEqual(runtime["enabled_tool_count"], len(read_only))
        self.assertEqual(runtime["enabled_tools_sha256"], enabled_tools_sha256(read_only))

        context = AgentRequestContext(
            services=self.app.state.services, candidate=self.candidate, actor_username="demo",
            chat_id="chat:whitelist-confirm", trace=self._trace("chat:whitelist-confirm"),
        )
        with bind_agent_context(context):
            blocked = confirm_application_change.invoke({"action_id": "ACT-SYNTHETIC"})
        self.assertTrue(blocked["blocked"])
        self.assertEqual(blocked["reason_code"], "CONFIRMATION_REQUIRED")

    def test_legacy_agentops_configuration_migrates_to_previous_all_tools_semantics(self) -> None:
        legacy_path = str(Path(self.temp.name) / "legacy-agentops.db")
        original = AgentOpsService(AgentOpsStore(legacy_path))
        state = original.store.release_state()
        stable = original.store.get_configuration(state["stable_version_id"])
        legacy_settings = dict(stable["settings"])
        legacy_settings.pop("enabled_tools")
        canonical = json.dumps(legacy_settings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                "UPDATE agent_config_versions SET settings_json = ?, settings_sha256 = ? WHERE version_id = ?",
                (canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest(), stable["version_id"]),
            )
            connection.commit()
        finally:
            connection.close()
        migrated = AgentOpsService(AgentOpsStore(legacy_path))
        restored = migrated.store.get_configuration(stable["version_id"])
        self.assertEqual(restored["settings"]["enabled_tools"], list(CAREER_TOOL_NAMES))
        self.assertTrue(any(item["event_type"] == "CONFIG_SCHEMA_MIGRATED" for item in migrated.store.list_audit()))

    def test_legacy_pending_action_constraint_migrates_without_losing_rows(self) -> None:
        job = self.job()
        application = self.application(job["job_id"], status="PLANNED")
        action = self.app.state.services.pending_actions.propose_application_transition(
            candidate_id=self.candidate["candidate_id"], actor_username="demo",
            chat_id="chat:legacy-pending", application_id=application["application_id"],
            target_status="APPLIED", expected_version=application["version"],
        )["action"]
        connection = sqlite3.connect(self.business_path)
        try:
            connection.execute("PRAGMA foreign_keys = OFF")
            current_sql = str(connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pending_actions'"
            ).fetchone()[0])
            old_sql = current_sql.replace(
                "('APPLICATION_TRANSITION', 'INTERVIEW_PROGRESSION')",
                "('APPLICATION_TRANSITION')",
            )
            connection.execute("ALTER TABLE pending_actions RENAME TO pending_actions_new")
            connection.execute(old_sql)
            connection.execute("INSERT INTO pending_actions SELECT * FROM pending_actions_new")
            connection.execute("DROP TABLE pending_actions_new")
            connection.execute(
                "CREATE INDEX idx_pending_actions_candidate_status ON pending_actions(candidate_id, status, expires_at, updated_at DESC)"
            )
            connection.commit()
        finally:
            connection.close()

        Database(self.business_path).initialize()
        migrated = self.app.state.services.pending_actions.get(self.candidate["candidate_id"], action["action_id"])
        self.assertEqual(migrated["action_type"], "APPLICATION_TRANSITION")
        connection = sqlite3.connect(self.business_path)
        try:
            table_sql = str(connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pending_actions'"
            ).fetchone()[0])
        finally:
            connection.close()
        self.assertIn("INTERVIEW_PROGRESSION", table_sql)

    def _trace(self, chat_id: str) -> TraceRecorder:
        settings = self.app.state.services.agentops.default_settings()
        return TraceRecorder.start(
            self.app.state.services.quality,
            actor_username="demo", candidate_id=self.candidate["candidate_id"], chat_id=chat_id,
            run_type="EVAL", model_name="synthetic", prompt_version=settings["prompt_version"],
            toolset_version=settings["toolset_version"], rule_version=settings["rule_version"], input_chars=0,
        )

    def test_interview_progression_is_atomic_and_repeat_confirm_is_idempotent(self) -> None:
        _, application, interview = self.interview_application()
        action = self.progression(application, interview)
        before = self.table_counts()
        self.assertEqual(self.app.state.services.applications.get(self.candidate["candidate_id"], application["application_id"])["status"], "INTERVIEW")
        first = self.app.state.services.pending_actions.confirm_from_frontend(
            candidate_id=self.candidate["candidate_id"], actor_username="demo", action_id=action["action_id"],
        )
        after = self.table_counts()
        result = first["action"]["result"]
        self.assertEqual(result["action_type"], "INTERVIEW_PROGRESSION")
        self.assertEqual(after["interview_rounds"], before["interview_rounds"] + 1)
        self.assertEqual(after["job_search_tasks"], before["job_search_tasks"] + 1)
        self.assertEqual(after["application_events"], before["application_events"] + 1)
        current = self.app.state.services.applications.get(self.candidate["candidate_id"], application["application_id"])
        rounds = self.app.state.services.interviews.list(self.candidate["candidate_id"], application["application_id"])
        tasks = self.app.state.services.tasks.list(self.candidate["candidate_id"])
        self.assertEqual(current["status"], "INTERVIEW")
        self.assertEqual(next(item for item in rounds if item["round_id"] == interview["round_id"])["status"], "COMPLETED")
        self.assertTrue(any(item["round_id"] == result["next_round_id"] and item["status"] == "SCHEDULED" for item in rounds))
        self.assertTrue(any(item["task_id"] == result["task_id"] and item["interview_round_id"] == result["next_round_id"] for item in tasks))
        self.assertEqual(current["events"][-1]["event_type"], "INTERVIEW_PROGRESSED")

        replay = self.app.state.services.pending_actions.confirm_from_frontend(
            candidate_id=self.candidate["candidate_id"], actor_username="demo", action_id=action["action_id"],
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(self.table_counts(), after)

    def test_interview_progression_blocks_stale_versions_wrong_round_and_cross_candidate(self) -> None:
        _, application, interview = self.interview_application()
        stale_application = self.progression(application, interview)
        connection = sqlite3.connect(self.business_path)
        try:
            connection.execute("UPDATE applications SET version = version + 1 WHERE application_id = ?", (application["application_id"],))
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(ConflictError):
            self.app.state.services.pending_actions.confirm_from_frontend(
                candidate_id=self.candidate["candidate_id"], actor_username="demo", action_id=stale_application["action_id"],
            )

        _, application2, interview2 = self.interview_application()
        stale_interview = self.progression(application2, interview2)
        self.app.state.services.interviews.update(self.candidate["candidate_id"], interview2["round_id"], {
            **interview2, "version": interview2["version"], "notes": "changed",
        })
        with self.assertRaises(ConflictError):
            self.app.state.services.pending_actions.confirm_from_frontend(
                candidate_id=self.candidate["candidate_id"], actor_username="demo", action_id=stale_interview["action_id"],
            )

        _, other_application, other_round = self.interview_application()
        with self.assertRaises(NotFoundError):
            self.progression(application2, other_round)

        self.app.state.services.auth.create_user("alice", "alice", role="user")
        alice = self.app.state.services.candidate.get("alice")
        alice_job = self.app.state.services.jobs.create(alice["candidate_id"], {
            "company_name": "隔离公司", "title": "隔离岗位", "status": "ACTIVE",
            "deadline": "2030-12-31", "required_skills": [], "preferred_skills": [],
        })
        alice_application = self.app.state.services.applications.create(alice["candidate_id"], "alice", {
            "job_id": alice_job["job_id"], "status": "APPLIED", "command_id": "hardening:alice:create",
        })["application"]
        alice_application = self.app.state.services.applications.transition(alice["candidate_id"], alice_application["application_id"], "alice", {
            "status": "INTERVIEW", "version": alice_application["version"], "command_id": "hardening:alice:interview",
        })["application"]
        alice_round = self.app.state.services.interviews.create(alice["candidate_id"], alice_application["application_id"], {
            "title": "一面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": future(1),
        })
        with self.assertRaises(NotFoundError):
            self.progression(alice_application, alice_round)

    def test_interview_progression_unconfirmed_and_sandbox_do_not_write(self) -> None:
        _, application, interview = self.interview_application()
        before = self.table_counts()
        action = self.progression(application, interview)
        after_propose = self.table_counts()
        self.assertEqual(after_propose["pending_actions"], before["pending_actions"] + 1)
        for table in ("applications", "application_events", "interview_rounds", "job_search_tasks"):
            self.assertEqual(after_propose[table], before[table])

        context = AgentRequestContext(
            services=self.app.state.services, candidate=self.candidate, actor_username="demo",
            chat_id="chat:sandbox-progression", trace=self._trace("chat:sandbox-progression"), sandbox=True,
        )
        with bind_agent_context(context):
            simulated = propose_application_change.invoke({
                "application_id": application["application_id"], "expected_version": application["version"],
                "action_type": "INTERVIEW_PROGRESSION", "current_round_id": interview["round_id"],
                "current_round_result": "通过", "next_round_type": "TECHNICAL", "next_round_title": "二面",
                "next_round_scheduled_at": future(7), "task_title": "准备二面", "task_due_at": future(6),
                "expected_interview_version": interview["version"],
            })
        self.assertTrue(simulated["sandbox"])
        self.assertFalse(simulated["persisted"])
        self.assertEqual(self.table_counts(), after_propose)
        self.assertEqual(action["status"], "PENDING")

    def test_interview_progression_failure_rolls_back_every_business_write(self) -> None:
        _, application, interview = self.interview_application()
        action = self.progression(application, interview, task_title="触发回滚")
        before = self.table_counts()
        connection = sqlite3.connect(self.business_path)
        try:
            connection.execute(
                """
                CREATE TRIGGER fail_progression_task
                BEFORE INSERT ON job_search_tasks
                WHEN NEW.title = '触发回滚'
                BEGIN SELECT RAISE(ABORT, 'forced rollback'); END
                """
            )
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.app.state.services.pending_actions.confirm_from_frontend(
                candidate_id=self.candidate["candidate_id"], actor_username="demo", action_id=action["action_id"],
            )
        self.assertEqual(self.table_counts(), before)
        current_round = next(item for item in self.app.state.services.interviews.list(
            self.candidate["candidate_id"], application["application_id"]
        ) if item["round_id"] == interview["round_id"])
        self.assertEqual(current_round["status"], "SCHEDULED")
        self.assertEqual(self.app.state.services.pending_actions.get(self.candidate["candidate_id"], action["action_id"])["status"], "PENDING")

    def test_agent_contract_eval_runs_all_eight_scripted_cases(self) -> None:
        response = self.admin.post("/api/agentops/evaluations/contract", json={})
        self.assertEqual(response.status_code, 200, response.text)
        evaluation = response.json()["evaluation"]
        self.assertEqual(evaluation["suite_version"], CONTRACT_SUITE_VERSION)
        self.assertEqual((evaluation["passed"], evaluation["total"]), (len(CONTRACT_CASES), len(CONTRACT_CASES)))
        self.assertEqual(evaluation["evaluation_kind"], "SCRIPTED_AGENT_CONTRACT")
        self.assertFalse(evaluation["live_model"])
        self.assertTrue(all(item["passed"] for item in evaluation["results"]))
        detail = self.admin.get(f"/api/agentops/evaluations/{evaluation['eval_run_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["evaluation"]["results"]), 8)

    def test_trace_contains_runtime_identity_but_not_payload_secrets(self) -> None:
        marker = "SYNTHETIC-RESUME-BODY-NOT-FOR-TRACE"
        result = self.app.state.services.agent.run(
            candidate=self.candidate, actor_username="demo",
            payload={"chat_id": "chat:trace-hardening", "message": marker},
        )
        serialized = json.dumps(result["trace"], ensure_ascii=False)
        self.assertNotIn(marker, serialized)
        for key in ("config_version_id", "release_channel", "release_generation", "enabled_tools_sha256"):
            self.assertIn(key, result["trace"])
        connection = sqlite3.connect(self.quality_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        for forbidden in (marker, "chain_of_thought", "DASHSCOPE_API_KEY"):
            self.assertNotIn(forbidden, dump)


if __name__ == "__main__":
    unittest.main()
