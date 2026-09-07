from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runner import AgentOutput, LangChainCareerAgentRunner
from agent.tools import CAREER_TOOL_NAMES
from api.main import create_app
from fastapi.testclient import TestClient


class AcceptanceRunner:
    available = True
    model_name = "final-hardening-acceptance"

    def __init__(self) -> None:
        self.histories: list[list[dict[str, str]]] = []

    def run(self, *, message: str, history: list[dict[str, str]], runtime_config: dict[str, Any] | None = None) -> AgentOutput:
        self.histories.append(list(history))
        return AgentOutput("合成验收回答")


class CaptureGraph:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.messages = list(payload["messages"])
        return {"messages": [type("Message", (), {"content": "ok", "usage_metadata": {}})()]}


def future(days: int) -> str:
    value = datetime.now(timezone.utc) + timedelta(days=days)
    return value.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        runner = AcceptanceRunner()
        app = create_app(
            db_path=str(root / "business.db"), quality_path=str(root / "quality.db"),
            agentops_path=str(root / "agentops.db"), session_secret="final-hardening-acceptance",
            agent_runner=runner,
        )
        demo = TestClient(app)
        admin = TestClient(app)
        try:
            check(demo.post("/api/auth/login", json={"username": "demo", "password": "demo"}).status_code == 200, "synthetic demo login")
            check(admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code == 200, "synthetic admin login")
            services = app.state.services
            candidate = services.candidate.get("demo")
            candidate = services.candidate.update("demo", {
                **candidate, "version": candidate["version"], "graduation_year": "2027",
                "preferred_cities": ["上海"], "skills": ["Python"],
                "preferences": {"languages": []}, "current_resume_parsed": {"languages": ["英语"]},
            })

            language_job = services.jobs.create(candidate["candidate_id"], {
                "company_name": "语言验收公司", "title": "Agent 工程师", "location": "上海",
                "graduation_year": "2027", "deadline": "2030-12-31", "required_skills": ["Python"],
                "preferred_skills": [], "source_metadata": {"phase2_parsed": {"hard_conditions": {"required_languages": ["English"]}}},
            })
            language_match = services.matching.match_job(candidate, language_job["job_id"])
            check(next(item for item in language_match["hard_conditions"] if item["name"] == "languages")["status"] == "PASS", "1. confirmed resume 英语 + JD English => PASS")

            closed_job = services.jobs.create(candidate["candidate_id"], {
                "company_name": "关闭验收公司", "title": "Agent 工程师", "location": "上海",
                "graduation_year": "2027", "deadline": "2030-12-31", "status": "CLOSED",
                "required_skills": ["Python"], "preferred_skills": [],
            })
            check(services.matching.match_job(candidate, closed_job["job_id"])["grade"] == "NOT_RECOMMENDED", "2. CLOSED + full skills => NOT_RECOMMENDED")

            candidate = services.candidate.update("demo", {**candidate, "version": candidate["version"], "skills": []})
            gap_jobs = [
                services.jobs.create(candidate["candidate_id"], {
                    "company_name": f"技能验收公司{index}", "title": f"后端工程师{index}", "location": "上海",
                    "graduation_year": "2027", "deadline": "2030-12-31",
                    "required_skills": [skill], "preferred_skills": [],
                })
                for index, skill in enumerate(("FastAPI", "Fast API"), 1)
            ]
            gap = services.skill_gaps.analyze(candidate, job_ids=[item["job_id"] for item in gap_jobs])
            canonical = [item for item in gap["skills"] if item["canonical_skill"] == "fastapi"]
            check(len(canonical) == 1 and canonical[0]["required_count"] == 2, "3. FastAPI / Fast API canonical aggregation")

            malformed = demo.post("/api/parsing/resume/preview", content="[]", headers={"content-type": "application/json"})
            check(400 <= malformed.status_code < 500, "4. malformed JSON shape => 4xx")

            memory_result = services.agent.run(
                candidate=candidate, actor_username="demo",
                payload={"chat_id": "chat:accept-memory", "message": "查看岗位", "current_job_id": language_job["job_id"]},
            )
            loaded_memory = demo.get("/api/agent/memory/chat:accept-memory").json()["memory"]
            live_job = demo.get(f"/api/jobs/{loaded_memory['current_job_id']}")
            check(loaded_memory["current_job_id"] == language_job["job_id"] and live_job.status_code == 200, "5. AgentMemory reloads refs and business object comes from official API")

            langchain_runner = LangChainCareerAgentRunner()
            langchain_runner.available = True
            graph = CaptureGraph()
            langchain_runner._graph_for = lambda settings: graph  # type: ignore[method-assign]
            history = [{"role": "user", "content": f"h{index}"} for index in range(20)]
            langchain_runner.run(message="current", history=history, runtime_config={"history_messages": 20})
            check(len(graph.messages) - 1 == 20, "6. history_messages=20 reaches model runner")

            read_only = list(CAREER_TOOL_NAMES[:8])
            schema = langchain_runner.tools_for({"enabled_tools": read_only})
            check("propose_application_change" not in schema and "confirm_application_change" not in schema, "7. read-only whitelist excludes write Tool schema")

            contract = services.quality_management.run_contract()
            check(contract["passed"] == contract["total"] == 8 and not contract["live_model"], "8. career-agent-contract-v1 scripted eval 8/8")

            interview_job = services.jobs.create(candidate["candidate_id"], {
                "company_name": "面试验收公司", "title": "Agent 工程师", "location": "上海",
                "graduation_year": "2027", "deadline": "2030-12-31", "required_skills": [], "preferred_skills": [],
            })
            application = services.applications.create(candidate["candidate_id"], "demo", {
                "job_id": interview_job["job_id"], "status": "APPLIED", "command_id": "acceptance:application:create",
            })["application"]
            application = services.applications.transition(candidate["candidate_id"], application["application_id"], "demo", {
                "status": "INTERVIEW", "version": application["version"], "command_id": "acceptance:application:interview",
            })["application"]
            current_round = services.interviews.create(candidate["candidate_id"], application["application_id"], {
                "round_type": "TECHNICAL", "title": "一面", "status": "SCHEDULED", "scheduled_at": future(1),
            })
            action = services.pending_actions.propose_interview_progression(
                candidate_id=candidate["candidate_id"], actor_username="demo", chat_id="chat:accept-progression",
                application_id=application["application_id"], current_round_id=current_round["round_id"],
                current_round_result="通过", next_round_type="TECHNICAL", next_round_title="二面",
                next_round_scheduled_at=future(7), task_title="准备二面", task_due_at=future(6),
                expected_application_version=application["version"], expected_interview_version=current_round["version"],
            )["action"]
            before_confirm = {
                "application": services.applications.get(candidate["candidate_id"], application["application_id"]),
                "rounds": services.interviews.list(candidate["candidate_id"], application["application_id"]),
                "tasks": services.tasks.list(candidate["candidate_id"]),
            }
            check(before_confirm["application"]["version"] == application["version"] and len(before_confirm["rounds"]) == 1, "9a. interview progression propose only; unconfirmed business state unchanged")
            confirmed = services.pending_actions.confirm_from_frontend(
                candidate_id=candidate["candidate_id"], actor_username="demo", action_id=action["action_id"],
            )
            progression_result = confirmed["action"]["result"]
            current_application = services.applications.get(candidate["candidate_id"], application["application_id"])
            rounds = services.interviews.list(candidate["candidate_id"], application["application_id"])
            tasks = services.tasks.list(candidate["candidate_id"])
            progression_ok = (
                current_application["status"] == "INTERVIEW"
                and next(item for item in rounds if item["round_id"] == current_round["round_id"])["status"] == "COMPLETED"
                and any(item["round_id"] == progression_result["next_round_id"] for item in rounds)
                and any(item["task_id"] == progression_result["task_id"] for item in tasks)
                and current_application["events"][-1]["event_type"] == "INTERVIEW_PROGRESSED"
            )
            check(progression_ok, "9b. confirm atomically completes round, creates next round/task/event and keeps INTERVIEW")
            counts_before_replay = (len(rounds), len(tasks), len(current_application["events"]))
            replay = services.pending_actions.confirm_from_frontend(
                candidate_id=candidate["candidate_id"], actor_username="demo", action_id=action["action_id"],
            )
            replay_application = services.applications.get(candidate["candidate_id"], application["application_id"])
            counts_after_replay = (
                len(services.interviews.list(candidate["candidate_id"], application["application_id"])),
                len(services.tasks.list(candidate["candidate_id"])),
                len(replay_application["events"]),
            )
            check(replay["idempotent_replay"] and counts_before_replay == counts_after_replay, "10. repeated confirm creates no duplicate business records")

            marker = "SYNTHETIC-PRIVATE-TRACE-MARKER"
            traced = services.agent.run(
                candidate=candidate, actor_username="demo",
                payload={"chat_id": "chat:accept-trace", "message": marker, "history": history},
            )
            serialized_trace = json.dumps(traced["trace"], ensure_ascii=False)
            connection = sqlite3.connect(root / "quality.db")
            try:
                quality_dump = "\n".join(connection.iterdump())
            finally:
                connection.close()
            trace_ok = (
                marker not in serialized_trace and marker not in quality_dump
                and "chain_of_thought" not in quality_dump and "DASHSCOPE_API_KEY" not in quality_dump
                and all(key in traced["trace"] for key in ("config_version_id", "release_channel", "release_generation"))
            )
            check(trace_ok, "11. Trace excludes payload/CoT/API key and records config identity")
            check(memory_result["trace"]["status"] == "SUCCESS", "acceptance trace completed")
        finally:
            demo.close()
            admin.close()

    print("FINAL HARDENING ACCEPTANCE: PASS (11/11 acceptance groups)")


if __name__ == "__main__":
    main()
