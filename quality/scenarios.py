from __future__ import annotations

from pathlib import Path
import tempfile
from typing import Any

from agent.runner import AgentOutput
from core.database import Database


class _OfflineRunner:
    available = True
    model_name = "phase5-fixed-scenario"

    def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        runtime_config: dict[str, Any] | None = None,
    ) -> AgentOutput:
        return AgentOutput("固定评测不调用外部模型。")


class FixedScenarioEvaluator:
    """Isolated deterministic fixture used by the Phase 5 eval control plane."""

    def __init__(self) -> None:
        from core.container import build_services

        self._temp = tempfile.TemporaryDirectory()
        root = Path(self._temp.name)
        database = Database(str(root / "business.db"))
        database.initialize()
        self.services = build_services(
            database,
            quality_path=str(root / "quality.db"),
            agentops_path=str(root / "agentops.db"),
            agent_runner=_OfflineRunner(),
        )
        self.services.auth.bootstrap_local_users()
        candidate = self.services.candidate.get("demo")
        self.candidate = self.services.candidate.update("demo", {
            **candidate,
            "version": candidate["version"],
            "graduation_year": "2027",
            "degree": "MSc",
            "preferred_cities": ["上海"],
            "skills": ["Python", "FastAPI"],
        })
        self.expired = self._job("过期样例", deadline="2000-01-01")
        self.wrong_year = self._job("届别样例", graduation_year="2028")
        self.full = self._job("全命中样例")
        self.gap = self._job("缺口样例", required_skills=["Python", "Django"])
        self._counter = 0

    def _job(self, company: str, **changes: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "company_name": company,
            "title": "AI 应用工程师",
            "location": "上海",
            "employment_type": "全职",
            "graduation_year": "2027",
            "deadline": "2030-12-31",
            "required_skills": ["Python", "FastAPI"],
            "preferred_skills": ["Vue 3"],
            "is_favorite": True,
        }
        payload.update(changes)
        return self.services.jobs.create(self.candidate["candidate_id"], payload)

    def _application(self, job_id: str, suffix: str) -> dict[str, Any]:
        return self.services.applications.create(
            self.candidate["candidate_id"],
            "demo",
            {
                "job_id": job_id,
                "status": "PLANNED",
                "command_id": f"phase5:eval:{suffix}",
            },
        )["application"]

    def evaluate(self, case: Any, sandbox: bool) -> tuple[bool, dict[str, Any]]:
        if not sandbox:
            return False, {"status": "sandbox_required"}
        if case.case_id == "hard_deadline_reject":
            result = self.services.matching.match_job(self.candidate, self.expired["job_id"])
            actual = {
                "grade": result["grade"],
                "failed": "deadline" if any(
                    item["name"] == "deadline" and item["status"] == "FAIL"
                    for item in result["hard_conditions"]
                ) else "",
            }
        elif case.case_id == "hard_graduation_reject":
            result = self.services.matching.match_job(self.candidate, self.wrong_year["job_id"])
            actual = {
                "grade": result["grade"],
                "failed": "graduation_year" if any(
                    item["name"] == "graduation_year" and item["status"] == "FAIL"
                    for item in result["hard_conditions"]
                ) else "",
            }
        elif case.case_id == "required_skill_full_match":
            result = self.services.matching.match_job(self.candidate, self.full["job_id"])
            actual = {"required_ratio": result["required_coverage"]["ratio"]}
        elif case.case_id == "required_skill_gap":
            result = self.services.matching.match_job(self.candidate, self.gap["job_id"])
            actual = {"missing_count": len(result["required_coverage"]["missing_skills"])}
        elif case.case_id == "compare_jobs":
            result = self.services.matching.compare(
                self.candidate, [self.full["job_id"], self.gap["job_id"]]
            )
            actual = {"item_count": len(result["items"])}
        elif case.case_id == "query_applications":
            if not self.services.applications.list(self.candidate["candidate_id"]):
                self._application(self.full["job_id"], "query-applications")
            actual = {
                "minimum_items": min(
                    1, len(self.services.applications.list(self.candidate["candidate_id"]))
                )
            }
        elif case.case_id == "confirmed_transition":
            self._counter += 1
            job = self._job(f"确认评测{self._counter}")
            application = self._application(job["job_id"], f"confirm-{self._counter}")
            action = self.services.pending_actions.propose_application_transition(
                candidate_id=self.candidate["candidate_id"],
                actor_username="demo",
                chat_id=f"chat:phase5-confirm-{self._counter}",
                application_id=application["application_id"],
                target_status="APPLIED",
                expected_version=1,
            )["action"]
            self.services.pending_actions.confirm_from_frontend(
                candidate_id=self.candidate["candidate_id"],
                actor_username="demo",
                action_id=action["action_id"],
            )
            current = self.services.applications.get(
                self.candidate["candidate_id"], application["application_id"]
            )
            actual = {"persisted": current["status"] == "APPLIED"}
        else:
            self._counter += 1
            job = self._job(f"未确认评测{self._counter}")
            application = self._application(job["job_id"], f"blocked-{self._counter}")
            self.services.pending_actions.propose_application_transition(
                candidate_id=self.candidate["candidate_id"],
                actor_username="demo",
                chat_id=f"chat:phase5-blocked-{self._counter}",
                application_id=application["application_id"],
                target_status="APPLIED",
                expected_version=1,
            )
            current = self.services.applications.get(
                self.candidate["candidate_id"], application["application_id"]
            )
            actual = {"persisted": current["status"] != "PLANNED"}
        return actual == case.expected, actual

    def close(self) -> None:
        self._temp.cleanup()

    def __enter__(self) -> "FixedScenarioEvaluator":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
