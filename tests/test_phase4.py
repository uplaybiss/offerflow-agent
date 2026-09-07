from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from typing import Any

from fastapi.testclient import TestClient

from agent.context import AgentRequestContext, bind_agent_context
from agent.runner import AgentOutput
from agent.tools import (
    CAREER_TOOLS,
    confirm_application_change,
    compare_jobs,
    get_candidate_360,
    propose_application_change,
    query_applications,
    search_jobs,
)
from api.main import create_app
from quality.eval import FIXED_CASES
from quality.trace import TraceRecorder


class ScriptedAgentRunner:
    available = True
    model_name = "scripted-career-agent"

    def run(self, *, message: str, history: list[dict[str, str]], runtime_config: dict[str, Any] | None = None) -> AgentOutput:
        if "提议" in message:
            applications = query_applications.invoke({"status": "", "include_timeline": False})["items"]
            item = applications[0]
            result = propose_application_change.invoke({
                "application_id": item["application_id"],
                "target_status": "APPLIED",
                "expected_version": item["version"],
                "next_action": "准备测评",
                "notes": "由测试 Agent 提议",
            })
            return AgentOutput(f"已生成确认卡 {result['action_id']}，未确认前不会修改投递。", 31, 18)
        if "未投递" in message:
            result = search_jobs.invoke({"query": "", "status": "ACTIVE", "favorite_only": True, "not_applied_only": True})
            return AgentOutput(f"找到 {result['item_count']} 个收藏且未投递岗位。", 24, 12)
        if "投递" in message:
            result = query_applications.invoke({"status": "", "include_timeline": True})
            return AgentOutput(f"当前有 {result['item_count']} 条投递。", 20, 10)
        result = get_candidate_360.invoke({})
        return AgentOutput(f"已读取实时候选人上下文，共 {result['item_count']} 个活对象。", 18, 9)


class Phase4TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        folder = Path(self.temp.name)
        self.db_path = str(folder / "phase4.db")
        self.quality_path = str(folder / "phase4-quality.db")
        self.app = create_app(
            db_path=self.db_path,
            quality_path=self.quality_path,
            session_secret="phase4-test",
            agent_runner=ScriptedAgentRunner(),
        )
        self.client = TestClient(self.app)
        login = self.client.post("/api/auth/login", json={"username": "demo", "password": "demo"})
        self.assertEqual(login.status_code, 200)
        current = self.client.get("/api/candidate").json()["candidate"]
        updated = self.client.put("/api/candidate", json={
            **current,
            "version": current["version"],
            "full_name": "王测试",
            "email": "wang.secret@example.test",
            "phone": "13800138000",
            "graduation_year": "2027",
            "degree": "MSc",
            "skills": ["Python", "FastAPI", "Vue 3"],
            "preferred_cities": ["上海"],
            "current_resume_text": "RESUME-PRIVATE-BODY-ALPHA",
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        self.candidate = updated.json()["candidate"]

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def create_job(self, *, company: str = "收藏科技", favorite: bool = True, required: list[str] | None = None) -> dict[str, Any]:
        response = self.client.post("/api/jobs", json={
            "company_name": company,
            "title": "AI 应用工程师",
            "location": "上海",
            "employment_type": "全职",
            "graduation_year": "2027",
            "deadline": "2030-12-31",
            "required_skills": required or ["Python", "FastAPI"],
            "preferred_skills": ["Vue 3"],
            "is_favorite": favorite,
            "description_text": "PRIVATE-JD-BODY-BETA",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["job"]

    def create_application(self, job_id: str) -> dict[str, Any]:
        response = self.client.post("/api/applications", json={
            "job_id": job_id, "status": "PLANNED", "command_id": "phase4:create:application",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["application"]

    def parse_stream(self, response: Any) -> list[dict[str, Any]]:
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.headers["content-type"].startswith("application/x-ndjson"))
        return [json.loads(line) for line in response.text.splitlines() if line]

    def trace(self, chat_id: str = "chat:test-context") -> TraceRecorder:
        return TraceRecorder.start(
            self.app.state.services.quality,
            actor_username="demo",
            candidate_id=self.candidate["candidate_id"],
            chat_id=chat_id,
            run_type="CHAT",
            model_name="test",
            prompt_version="test",
            toolset_version="test",
            rule_version="test",
            input_chars=0,
        )

    def test_schema_adds_only_phase4_memory_and_pending_action_business_tables(self) -> None:
        self.assertEqual(set(self.app.state.services.database.table_names()), {
            "users", "candidate_profiles", "jobs", "applications", "application_events",
            "interview_rounds", "job_search_tasks", "agent_memories", "pending_actions",
            "resume_versions", "chat_threads", "chat_messages",
        })
        with self.app.state.services.quality.connection() as connection:
            tables = {str(row["name"]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )}
        self.assertEqual(tables, {"agent_runs", "trace_events", "eval_runs", "eval_case_results", "eval_baselines"})

    def test_catalog_has_exactly_ten_tools_and_never_accepts_candidate_id(self) -> None:
        expected = {
            "get_candidate_360", "search_jobs", "get_job_detail", "analyze_job_match", "compare_jobs",
            "analyze_skill_gaps", "query_applications", "list_upcoming_tasks",
            "analyze_resume_for_job", "propose_application_change", "propose_task_change",
            "confirm_application_change",
        }
        self.assertEqual({item.name for item in CAREER_TOOLS}, expected)
        self.assertEqual(len(CAREER_TOOLS), 12)
        self.assertTrue(all("candidate_id" not in item.args for item in CAREER_TOOLS))

    def test_agent_compare_tool_supports_five_while_existing_ui_api_keeps_four(self) -> None:
        jobs = [self.create_job(company=f"对比科技{index}") for index in range(5)]
        context = AgentRequestContext(
            services=self.app.state.services, candidate=self.candidate, actor_username="demo",
            chat_id="chat:compare-five", trace=self.trace("chat:compare-five"),
        )
        with bind_agent_context(context):
            result = compare_jobs.invoke({"job_ids": [item["job_id"] for item in jobs]})
        self.assertEqual(result["item_count"], 5)
        existing_api = self.client.post("/api/jobs/compare", json={"job_ids": [item["job_id"] for item in jobs]})
        self.assertEqual(existing_api.status_code, 400)

    def test_agent_reads_real_unapplied_favorites_over_ndjson(self) -> None:
        applied_job = self.create_job(company="已投科技")
        self.create_application(applied_job["job_id"])
        self.create_job(company="未投科技")
        response = self.client.post("/api/agent/chat/stream", json={
            "chat_id": "chat:read-favorites", "message": "列出收藏但未投递的岗位", "history": [],
        })
        events = self.parse_stream(response)
        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual(events[-1]["type"], "complete")
        self.assertIn("找到 1 个", events[-1]["answer"])
        tools = [item["tool_name"] for item in events[-1]["trace"]["events"] if item["event_type"] == "TOOL_END"]
        self.assertEqual(tools, ["search_jobs"])

    def test_proposal_is_idempotent_and_does_not_change_application(self) -> None:
        job = self.create_job()
        application = self.create_application(job["job_id"])
        payload = {"chat_id": "chat:propose-write", "message": "提议把投递改为已投递", "history": []}
        first = self.parse_stream(self.client.post("/api/agent/chat/stream", json=payload))
        second = self.parse_stream(self.client.post("/api/agent/chat/stream", json=payload))
        cards = [item["action"] for item in first if item["type"] == "pending_action"]
        self.assertEqual(len(cards), 1)
        self.assertEqual([item for item in second if item["type"] == "pending_action"][0]["action"]["action_id"], cards[0]["action_id"])
        current = self.client.get(f"/api/applications/{application['application_id']}").json()["application"]
        self.assertEqual(current["status"], "PLANNED")
        self.assertEqual(len(current["events"]), 1)
        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0], 1)
        finally:
            connection.close()

    def test_model_cannot_self_confirm_but_frontend_confirmation_is_atomic_and_idempotent(self) -> None:
        job = self.create_job()
        application = self.create_application(job["job_id"])
        stream = self.parse_stream(self.client.post("/api/agent/chat/stream", json={
            "chat_id": "chat:confirm-write", "message": "提议把投递改为已投递", "history": [],
        }))
        action = next(item["action"] for item in stream if item["type"] == "pending_action")
        context = AgentRequestContext(
            services=self.app.state.services, candidate=self.candidate, actor_username="demo",
            chat_id="chat:confirm-write", trace=self.trace("chat:model-bypass"),
        )
        with bind_agent_context(context):
            blocked = confirm_application_change.invoke({"action_id": action["action_id"]})
        self.assertTrue(blocked["blocked"])
        self.assertFalse(blocked["persisted"])
        unchanged = self.client.get(f"/api/applications/{application['application_id']}").json()["application"]
        self.assertEqual(unchanged["status"], "PLANNED")

        confirmed = self.client.post(f"/api/pending-actions/{action['action_id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        current = self.client.get(f"/api/applications/{application['application_id']}").json()["application"]
        self.assertEqual(current["status"], "APPLIED")
        self.assertEqual(current["version"], 2)
        self.assertEqual(len(current["events"]), 2)
        self.assertEqual(current["events"][-1]["event_type"], "AGENT_STATUS_CHANGED")
        replay = self.client.post(f"/api/pending-actions/{action['action_id']}/confirm")
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["result"]["idempotent_replay"])
        after = self.client.get(f"/api/applications/{application['application_id']}").json()["application"]
        self.assertEqual(after["version"], 2)
        self.assertEqual(len(after["events"]), 2)
        self.assertNotIn("confirmation_grant", confirmed.text)
        connection = sqlite3.connect(self.db_path)
        try:
            grant_hash, request_hash = connection.execute(
                "SELECT confirmation_grant_hash, request_hash FROM pending_actions WHERE action_id = ?",
                (action["action_id"],),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(len(grant_hash), 64)
        self.assertEqual(len(request_hash), 64)
        self.assertNotEqual(grant_hash, request_hash)

    def test_expired_confirmation_card_is_not_executable(self) -> None:
        job = self.create_job()
        application = self.create_application(job["job_id"])
        stream = self.parse_stream(self.client.post("/api/agent/chat/stream", json={
            "chat_id": "chat:expired-card", "message": "提议把投递改为已投递",
        }))
        action = next(item["action"] for item in stream if item["type"] == "pending_action")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "UPDATE pending_actions SET expires_at = '2000-01-01T00:00:00.000Z' WHERE action_id = ?",
                (action["action_id"],),
            )
            connection.commit()
        finally:
            connection.close()
        listed = self.client.get("/api/pending-actions").json()["items"]
        expired = next(item for item in listed if item["action_id"] == action["action_id"])
        self.assertEqual(expired["status"], "EXPIRED")
        self.assertFalse(expired["requires_confirmation"])
        response = self.client.post(f"/api/pending-actions/{action['action_id']}/confirm")
        self.assertEqual(response.status_code, 409)
        current = self.client.get(f"/api/applications/{application['application_id']}").json()["application"]
        self.assertEqual(current["status"], "PLANNED")
        self.assertEqual(len(current["events"]), 1)

    def test_stale_confirmation_card_cannot_overwrite_newer_application(self) -> None:
        job = self.create_job()
        application = self.create_application(job["job_id"])
        stream = self.parse_stream(self.client.post("/api/agent/chat/stream", json={
            "chat_id": "chat:stale-card", "message": "提议把投递改为已投递", "history": [],
        }))
        action = next(item["action"] for item in stream if item["type"] == "pending_action")
        manual = self.client.post(f"/api/applications/{application['application_id']}/transitions", json={
            "status": "APPLIED", "version": 1, "command_id": "phase4:manual:advance",
        })
        self.assertEqual(manual.status_code, 200, manual.text)
        stale = self.client.post(f"/api/pending-actions/{action['action_id']}/confirm")
        self.assertEqual(stale.status_code, 409)
        current = self.client.get(f"/api/applications/{application['application_id']}").json()["application"]
        self.assertEqual(current["status"], "APPLIED")
        self.assertEqual(current["version"], 2)
        self.assertEqual(len(current["events"]), 2)

    def test_sandbox_blocks_both_write_tools(self) -> None:
        job = self.create_job()
        application = self.create_application(job["job_id"])
        result = self.app.state.services.agent.run(
            candidate=self.candidate,
            actor_username="demo",
            payload={"chat_id": "chat:sandbox-eval", "message": "提议把投递改为已投递"},
            sandbox=True,
            run_type="EVAL",
        )
        self.assertEqual(result["pending_actions"], [])
        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0], 0)
        finally:
            connection.close()
        current = self.client.get(f"/api/applications/{application['application_id']}").json()["application"]
        self.assertEqual(current["status"], "PLANNED")

        context = AgentRequestContext(
            services=self.app.state.services, candidate=self.candidate, actor_username="demo",
            chat_id="chat:sandbox-confirm", trace=self.trace("chat:sandbox-confirm"), sandbox=True,
        )
        with bind_agent_context(context):
            confirm_result = confirm_application_change.invoke({"action_id": "ACT-NOT-REAL"})
        self.assertFalse(confirm_result["persisted"])

    def test_memory_uses_live_refs_and_controlled_goal_not_chat_or_pii(self) -> None:
        job = self.create_job()
        response = self.client.post("/api/agent/chat/stream", json={
            "chat_id": "chat:privacy-memory",
            "message": "我是王测试，邮箱 wang.secret@example.test，电话 13800138000，请比较岗位。RESUME-SECRET-GAMMA",
            "current_job_id": job["job_id"],
        })
        events = self.parse_stream(response)
        memory = events[-1]["memory"]
        self.assertEqual(memory["current_job_id"], job["job_id"])
        self.assertEqual(memory["last_user_goal"], "岗位检索与比较")
        serialized = json.dumps(memory, ensure_ascii=False)
        for forbidden in ("王测试", "wang.secret@example.test", "13800138000", "RESUME-SECRET-GAMMA"):
            self.assertNotIn(forbidden, serialized)

    def test_trace_persists_only_allowlisted_metadata_without_pii_cot_or_source_text(self) -> None:
        self.create_job()
        response = self.client.post("/api/agent/chat/stream", json={
            "chat_id": "chat:privacy-trace",
            "message": "王测试 wang.secret@example.test 13800138000 RESUME-PRIVATE-BODY-ALPHA chain_of_thought 查投递",
        })
        self.parse_stream(response)
        connection = sqlite3.connect(self.quality_path)
        try:
            dump = "\n".join(connection.iterdump())
        finally:
            connection.close()
        for forbidden in (
            "王测试", "wang.secret@example.test", "13800138000", "RESUME-PRIVATE-BODY-ALPHA",
            "PRIVATE-JD-BODY-BETA", "chain_of_thought",
        ):
            self.assertNotIn(forbidden, dump)
        self.assertIn("query_applications", dump)

    def test_other_candidate_cannot_read_or_confirm_pending_action(self) -> None:
        job = self.create_job()
        self.create_application(job["job_id"])
        stream = self.parse_stream(self.client.post("/api/agent/chat/stream", json={
            "chat_id": "chat:isolation", "message": "提议把投递改为已投递",
        }))
        action_id = next(item["action"]["action_id"] for item in stream if item["type"] == "pending_action")
        admin = TestClient(self.app)
        self.assertEqual(admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code, 200)
        self.assertEqual(admin.post("/api/auth/users", json={"username": "alice", "password": "alice", "role": "user"}).status_code, 201)
        alice = TestClient(self.app)
        self.assertEqual(alice.post("/api/auth/login", json={"username": "alice", "password": "alice"}).status_code, 200)
        self.assertEqual(alice.get("/api/pending-actions").json()["items"], [])
        self.assertEqual(alice.post(f"/api/pending-actions/{action_id}/confirm").status_code, 404)
        admin.close(); alice.close()

    def test_fixed_evaluation_runs_in_sandbox_and_replay_matches_baseline(self) -> None:
        seen: list[tuple[str, bool]] = []

        def evaluator(case: Any, sandbox: bool) -> tuple[bool, dict[str, Any]]:
            seen.append((case.case_id, sandbox))
            return True, dict(case.expected)

        first = self.app.state.services.evaluation.run(evaluator, baseline_name="phase4-test")
        replay = self.app.state.services.evaluation.replay(evaluator, baseline_name="phase4-test")
        self.assertEqual(first["passed"], 8)
        self.assertEqual(first["total"], len(FIXED_CASES))
        self.assertTrue(first["sandbox"])
        self.assertEqual(replay["baseline"]["status"], "MATCH")
        self.assertTrue(replay["replay"])
        self.assertTrue(all(sandbox for _, sandbox in seen))

    def test_frontend_keeps_agent_page_after_sixth_agentops_page_is_added(self) -> None:
        src = Path(__file__).resolve().parents[1] / "frontend" / "src"
        sidebar = (src / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
        self.assertEqual(sidebar.count("{ id: '"), 7)
        self.assertIn("求职 Agent", sidebar)
        view = (src / "views" / "CareerAgentView.vue").read_text(encoding="utf-8")
        for term in ("/api/agent/chat/stream", "/confirm", "待你确认", "最近对话", "current_application_id"):
            self.assertIn(term, view)
        self.assertNotIn("Trace 摘要", view)
        api_source = (src / "api.ts").read_text(encoding="utf-8")
        self.assertIn("response.body.getReader", api_source)


if __name__ == "__main__":
    unittest.main()
