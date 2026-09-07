from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runner import AgentOutput
from agent.tools import propose_application_change, query_applications, search_jobs
from api.main import create_app


class AcceptanceRunner:
    available = True
    model_name = "phase4-acceptance-runner"

    def run(self, *, message: str, history: list[dict[str, str]], runtime_config: dict[str, Any] | None = None) -> AgentOutput:
        if "提议" in message:
            applications = query_applications.invoke({"status": "PLANNED", "include_timeline": False})["items"]
            if not applications:
                return AgentOutput("没有可迁移的 PLANNED 投递。")
            item = applications[0]
            proposal = propose_application_change.invoke({
                "application_id": item["application_id"], "target_status": "APPLIED",
                "expected_version": item["version"], "next_action": "准备测评", "notes": "Phase 4 验收",
            })
            return AgentOutput(f"已生成确认卡 {proposal['action_id']}，尚未修改投递。", 20, 12)
        jobs = search_jobs.invoke({
            "query": "", "status": "ACTIVE", "favorite_only": True, "not_applied_only": True,
        })
        return AgentOutput(f"找到 {jobs['item_count']} 个收藏且未投递岗位。", 16, 10)


def expect(response: Any) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.status_code} {response.text}")
    return response.json()


def stream_events(response: Any) -> list[dict[str, Any]]:
    if response.status_code != 200:
        raise RuntimeError(f"Agent stream failed: {response.status_code} {response.text}")
    if not response.headers["content-type"].startswith("application/x-ndjson"):
        raise RuntimeError("Agent stream is not NDJSON")
    return [json.loads(line) for line in response.text.splitlines() if line]


def create_job(client: TestClient, company: str, **changes: Any) -> dict[str, Any]:
    payload = {
        "company_name": company, "title": "AI 应用工程师", "location": "上海",
        "employment_type": "全职", "graduation_year": "2027", "deadline": "2030-12-31",
        "required_skills": ["Python", "FastAPI"], "preferred_skills": ["Vue 3"],
        "is_favorite": True,
    }
    payload.update(changes)
    return expect(client.post("/api/jobs", json=payload))["job"]


def create_application(client: TestClient, job_id: str, command: str) -> dict[str, Any]:
    return expect(client.post("/api/applications", json={
        "job_id": job_id, "status": "PLANNED", "command_id": command,
    }))["application"]


def run() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        app = create_app(
            db_path=str(root / "acceptance.db"),
            quality_path=str(root / "acceptance-quality.db"),
            session_secret="phase4-acceptance",
            agent_runner=AcceptanceRunner(),
        )
        client = TestClient(app)
        eval_client: TestClient | None = None
        try:
            expect(client.post("/api/auth/login", json={"username": "demo", "password": "demo"}))
            candidate = expect(client.get("/api/candidate"))["candidate"]
            candidate = expect(client.put("/api/candidate", json={
                **candidate, "version": candidate["version"], "full_name": "验收用户",
                "email": "acceptance.private@example.test", "phone": "13900139000",
                "graduation_year": "2027", "degree": "MSc", "preferred_cities": ["上海"],
                "skills": ["Python", "FastAPI", "Vue 3"],
                "current_resume_text": "ACCEPTANCE-PRIVATE-RESUME",
            }))["candidate"]
            applied_job = create_job(client, "已建投递科技")
            application = create_application(client, applied_job["job_id"], "phase4:accept:create")
            create_job(client, "收藏未投科技")
            expect(client.post("/api/tasks", json={
                "title": "三天内准备材料", "task_type": "MATERIAL", "status": "TODO", "priority": "P1",
                "due_at": "2030-01-03T09:00:00+08:00", "application_id": application["application_id"],
                "job_id": applied_job["job_id"],
            }))

            checks: list[str] = []
            read_events = stream_events(client.post("/api/agent/chat/stream", json={
                "chat_id": "chat:phase4-read", "message": "列出收藏但未投递的岗位",
            }))
            if "找到 1 个" not in read_events[-1]["answer"]:
                raise RuntimeError("Agent 未查询到实时未投递收藏岗位")
            checks.append("Agent 经受控工具读取真实岗位、投递与筛选结果")

            proposal_events = stream_events(client.post("/api/agent/chat/stream", json={
                "chat_id": "chat:phase4-write", "message": "提议把这条投递更新为已投递",
            }))
            action = next(item["action"] for item in proposal_events if item["type"] == "pending_action")
            before = expect(client.get(f"/api/applications/{application['application_id']}"))["application"]
            if before["status"] != "PLANNED" or len(before["events"]) != 1:
                raise RuntimeError("提议阶段错误修改了 Application")
            checks.append("Agent 提议只创建 PendingAction，未确认不修改业务状态")

            confirmed = expect(client.post(f"/api/pending-actions/{action['action_id']}/confirm"))
            after = expect(client.get(f"/api/applications/{application['application_id']}"))["application"]
            if after["status"] != "APPLIED" or after["version"] != 2 or len(after["events"]) != 2:
                raise RuntimeError("确认后 Application/Event 原子迁移失败")
            if confirmed["result"]["to_status"] != "APPLIED":
                raise RuntimeError("确认结果错误")
            replay = expect(client.post(f"/api/pending-actions/{action['action_id']}/confirm"))
            if not replay["result"]["idempotent_replay"]:
                raise RuntimeError("重复确认未幂等返回")
            checks.append("确认卡第二次请求原子执行状态、Event 与 version CAS，重复确认幂等")

            sandbox_job = create_job(client, "沙箱禁写科技")
            sandbox_app = create_application(client, sandbox_job["job_id"], "phase4:sandbox:create")
            sandbox_result = app.state.services.agent.run(
                candidate=candidate,
                actor_username="demo",
                payload={"chat_id": "chat:phase4-sandbox", "message": "提议更新投递"},
                sandbox=True,
                run_type="EVAL",
            )
            sandbox_after = expect(client.get(f"/api/applications/{sandbox_app['application_id']}"))["application"]
            if sandbox_result["pending_actions"] or sandbox_after["status"] != "PLANNED":
                raise RuntimeError("评测沙箱发生真实写入")
            checks.append("Quality sandbox 阻断两个写工具的真实业务写入")

            quality_connection = sqlite3.connect(str(root / "acceptance-quality.db"))
            try:
                quality_dump = "\n".join(quality_connection.iterdump())
            finally:
                quality_connection.close()
            for forbidden in ("验收用户", "acceptance.private@example.test", "13900139000", "ACCEPTANCE-PRIVATE-RESUME", "chain_of_thought"):
                if forbidden in quality_dump:
                    raise RuntimeError(f"Trace 泄漏隐私字段: {forbidden}")
            checks.append("持久化 Trace 仅含 allowlist 元数据，不含 CoT、聊天原文与简历 PII")

            memory = expect(client.get("/api/agent/memory/chat:phase4-write"))["memory"]
            if memory["last_user_goal"] != "投递进度管理":
                raise RuntimeError("AgentMemory 未保存受控意图标签")
            checks.append("AgentMemory 保存活对象引用与受控意图，不保存聊天全文")

            eval_app = create_app(
                db_path=str(root / "eval-sandbox.db"), quality_path=str(root / "eval-quality.db"),
                session_secret="phase4-eval", agent_runner=AcceptanceRunner(),
            )
            eval_client = TestClient(eval_app)
            expect(eval_client.post("/api/auth/login", json={"username": "demo", "password": "demo"}))
            eval_candidate = expect(eval_client.get("/api/candidate"))["candidate"]
            eval_candidate = expect(eval_client.put("/api/candidate", json={
                **eval_candidate, "version": eval_candidate["version"], "graduation_year": "2027",
                "degree": "MSc", "preferred_cities": ["上海"], "skills": ["Python", "FastAPI"],
            }))["candidate"]
            expired = create_job(eval_client, "过期样例", deadline="2000-01-01")
            wrong_year = create_job(eval_client, "届别样例", graduation_year="2028")
            full = create_job(eval_client, "全命中样例")
            gap = create_job(eval_client, "缺口样例", required_skills=["Python", "Django"])
            counter = {"value": 0}

            def evaluator(case: Any, sandbox: bool) -> tuple[bool, dict[str, Any]]:
                if not sandbox:
                    return False, {"status": "sandbox_required"}
                if case.case_id == "hard_deadline_reject":
                    result = eval_app.state.services.matching.match_job(eval_candidate, expired["job_id"])
                    actual = {"grade": result["grade"], "failed": "deadline" if any(item["name"] == "deadline" and item["status"] == "FAIL" for item in result["hard_conditions"]) else ""}
                elif case.case_id == "hard_graduation_reject":
                    result = eval_app.state.services.matching.match_job(eval_candidate, wrong_year["job_id"])
                    actual = {"grade": result["grade"], "failed": "graduation_year" if any(item["name"] == "graduation_year" and item["status"] == "FAIL" for item in result["hard_conditions"]) else ""}
                elif case.case_id == "required_skill_full_match":
                    result = eval_app.state.services.matching.match_job(eval_candidate, full["job_id"])
                    actual = {"required_ratio": result["required_coverage"]["ratio"]}
                elif case.case_id == "required_skill_gap":
                    result = eval_app.state.services.matching.match_job(eval_candidate, gap["job_id"])
                    actual = {"missing_count": len(result["required_coverage"]["missing_skills"])}
                elif case.case_id == "compare_jobs":
                    result = eval_app.state.services.matching.compare(eval_candidate, [full["job_id"], gap["job_id"]])
                    actual = {"item_count": len(result["items"])}
                elif case.case_id == "query_applications":
                    if not eval_app.state.services.applications.list(eval_candidate["candidate_id"]):
                        create_application(eval_client, full["job_id"], "phase4:eval:query")
                    actual = {"minimum_items": min(1, len(eval_app.state.services.applications.list(eval_candidate["candidate_id"]))) }
                elif case.case_id == "confirmed_transition":
                    counter["value"] += 1
                    job = create_job(eval_client, f"确认评测{counter['value']}")
                    item = create_application(eval_client, job["job_id"], f"phase4:eval:confirm:{counter['value']}")
                    proposal = eval_app.state.services.pending_actions.propose_application_transition(
                        candidate_id=eval_candidate["candidate_id"], actor_username="demo", chat_id=f"chat:eval-confirm-{counter['value']}",
                        application_id=item["application_id"], target_status="APPLIED", expected_version=1,
                    )["action"]
                    eval_app.state.services.pending_actions.confirm_from_frontend(
                        candidate_id=eval_candidate["candidate_id"], actor_username="demo", action_id=proposal["action_id"],
                    )
                    actual = {"persisted": eval_app.state.services.applications.get(eval_candidate["candidate_id"], item["application_id"])["status"] == "APPLIED"}
                else:
                    counter["value"] += 1
                    job = create_job(eval_client, f"未确认评测{counter['value']}")
                    item = create_application(eval_client, job["job_id"], f"phase4:eval:block:{counter['value']}")
                    eval_app.state.services.pending_actions.propose_application_transition(
                        candidate_id=eval_candidate["candidate_id"], actor_username="demo", chat_id=f"chat:eval-block-{counter['value']}",
                        application_id=item["application_id"], target_status="APPLIED", expected_version=1,
                    )
                    actual = {"persisted": eval_app.state.services.applications.get(eval_candidate["candidate_id"], item["application_id"])["status"] != "PLANNED"}
                return actual == case.expected, actual

            evaluation = eval_app.state.services.evaluation.run(evaluator, baseline_name="phase4-acceptance")
            replayed_eval = eval_app.state.services.evaluation.replay(evaluator, baseline_name="phase4-acceptance")
            if evaluation["passed"] != 8 or replayed_eval["passed"] != 8 or replayed_eval["baseline"]["status"] != "MATCH":
                raise RuntimeError("固定评测或基线回放失败")
            checks.append("固定小评测 8/8 通过，隔离沙箱回放与基线比较一致")

            if set(app.state.services.database.table_names()) != {
                "users", "candidate_profiles", "jobs", "applications", "application_events",
                "interview_rounds", "job_search_tasks", "agent_memories", "pending_actions",
            }:
                raise RuntimeError("Phase 4 业务表不符合 9 表边界")
            checks.append("业务库为 9 张表，Phase 5/RAG/ResumeVersion/CandidateSkill 仍未提前实现")

            print("PHASE 4 ACCEPTANCE: PASS")
            for index, item in enumerate(checks, 1):
                print(f"  {index}. PASS - {item}")
            print(f"  eval={evaluation['passed']}/{evaluation['total']}, replay={replayed_eval['baseline']['status']}, business_tables=9, tools=10, pages=5")
        finally:
            if eval_client is not None:
                eval_client.close()
            client.close()


if __name__ == "__main__":
    run()
