from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from typing import Any

from fastapi.testclient import TestClient

from api.main import create_app
from core.database import Database
from core.time import configured_timezone


class Phase3TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "phase3.db")
        self.app = create_app(db_path=self.db_path, session_secret="phase3-test")
        self.client = TestClient(self.app)
        login = self.client.post("/api/auth/login", json={"username": "demo", "password": "demo"})
        self.assertEqual(login.status_code, 200)
        candidate = self.client.get("/api/candidate").json()["candidate"]
        updated = self.client.put("/api/candidate", json={
            **candidate,
            "version": candidate["version"],
            "graduation_year": "2027",
            "degree": "MSc",
            "preferred_cities": ["上海"],
            "skills": ["Python", "FastAPI", "Vue 3"],
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        self.sequence = 0

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def deadline(self, days: int = 10) -> str:
        return (datetime.now(configured_timezone()).date() + timedelta(days=days)).isoformat()

    def utc_time(self, days: int = 0, hours: int = 0) -> str:
        value = datetime.now(timezone.utc) + timedelta(days=days, hours=hours)
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")

    def create_job(self, **changes: Any) -> dict[str, Any]:
        self.sequence += 1
        payload: dict[str, Any] = {
            "company_name": f"Phase3 Company {self.sequence}",
            "title": f"AI Engineer {self.sequence}",
            "location": "上海",
            "employment_type": "全职",
            "recruitment_cycle": "2027 届秋招",
            "graduation_year": "2027",
            "deadline": self.deadline(),
            "description_text": "Python FastAPI",
            "required_skills": ["Python"],
            "preferred_skills": ["Vue 3"],
            "source_type": "MANUAL",
            "source_name": "手工记录",
            "source_url": f"https://example.test/jobs/{self.sequence}",
            "external_job_id": f"P3-{self.sequence}",
            "company_career_url": "https://example.test/careers",
            "source_metadata": {},
            "is_favorite": True,
        }
        payload.update(changes)
        response = self.client.post("/api/jobs", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["job"]

    def create_application(self, job_id: str, status: str = "PLANNED") -> dict[str, Any]:
        self.sequence += 1
        response = self.client.post("/api/applications", json={
            "job_id": job_id,
            "status": status,
            "next_action": "准备材料",
            "notes": "Phase 3 test",
            "command_id": f"phase3:create:{self.sequence:04d}",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["application"]

    def test_existing_phase2_database_is_migrated_through_phase4(self) -> None:
        old_path = str(Path(self.temp.name) / "phase2-existing.db")
        connection = sqlite3.connect(old_path)
        try:
            connection.execute(
                """
                CREATE TABLE job_search_tasks (
                    task_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, job_id TEXT,
                    application_id TEXT, interview_round_id TEXT, title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '', task_type TEXT NOT NULL DEFAULT 'GENERAL',
                    status TEXT NOT NULL DEFAULT 'TODO', priority TEXT NOT NULL DEFAULT 'P2',
                    due_at TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()
        database = Database(old_path)
        database.initialize()
        self.assertEqual(len(database.table_names()), 12)
        with database.connection() as connection:
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(job_search_tasks)")}
            indexes = {str(row["name"]) for row in connection.execute("PRAGMA index_list(job_search_tasks)")}
        self.assertTrue({"origin", "suggestion_key", "suggestion_source", "suggestion_payload_json"} <= columns)
        self.assertIn("idx_tasks_suggestion_key", indexes)

    def test_suggestions_cover_deadline_assessment_and_interview_with_trace(self) -> None:
        job = self.create_job()
        application = self.create_application(job["job_id"])
        assessment = self.client.post(f"/api/applications/{application['application_id']}/interviews", json={
            "title": "在线测评", "round_type": "ASSESSMENT", "status": "SCHEDULED", "scheduled_at": self.utc_time(days=3),
        })
        interview = self.client.post(f"/api/applications/{application['application_id']}/interviews", json={
            "title": "技术一面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": self.utc_time(days=5),
        })
        self.assertEqual((assessment.status_code, interview.status_code), (201, 201))
        response = self.client.get("/api/task-suggestions")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["config"]["persistence"], "preview_until_user_accepts")
        self.assertEqual({item["source"]["type"] for item in body["items"]}, {"JOB_DEADLINE", "ASSESSMENT_TIME", "INTERVIEW_TIME"})
        self.assertEqual(len({item["suggestion_key"] for item in body["items"]}), 3)
        for item in body["items"]:
            self.assertFalse(item["persisted"])
            self.assertTrue(item["requires_confirmation"])
            self.assertEqual(item["trace"]["rule_version"], "task_suggestion_v1")
        self.assertEqual(self.client.get("/api/tasks").json()["items"], [])

    def test_accepting_suggestion_is_idempotent_and_retained_task_stays_editable(self) -> None:
        job = self.create_job()
        suggestion = next(
            item for item in self.client.get("/api/task-suggestions").json()["items"]
            if item["source"]["type"] == "JOB_DEADLINE"
        )
        first = self.client.post(f"/api/task-suggestions/{suggestion['suggestion_key']}/accept")
        second = self.client.post(f"/api/task-suggestions/{suggestion['suggestion_key']}/accept")
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertFalse(first.json()["idempotent_replay"])
        self.assertTrue(second.json()["idempotent_replay"])
        task = first.json()["task"]
        self.assertEqual(task["origin"], "SUGGESTED")
        self.assertEqual(task["suggestion_source"], "JOB_DEADLINE")
        self.assertEqual(task["suggestion_payload"]["trace"]["rule_version"], "task_suggestion_v1")
        self.assertEqual(len(self.client.get("/api/tasks").json()["items"]), 1)
        self.assertEqual(self.client.get("/api/task-suggestions").json()["items"], [])
        edited = self.client.patch(f"/api/tasks/{task['task_id']}", json={
            **task, "version": task["version"], "title": "我调整后的投递准备", "priority": "P3",
        })
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["task"]["title"], "我调整后的投递准备")
        self.assertEqual(edited.json()["task"]["suggestion_key"], task["suggestion_key"])

    def test_applied_job_no_longer_generates_deadline_suggestion(self) -> None:
        job = self.create_job()
        self.create_application(job["job_id"], status="APPLIED")
        self.assertEqual(self.client.get("/api/task-suggestions").json()["items"], [])

    def test_workbench_exposes_funnel_recent_interviews_and_overdue_tasks(self) -> None:
        planned_job = self.create_job(deadline="")
        applied_job = self.create_job(deadline="")
        interview_job = self.create_job(deadline="")
        self.create_application(planned_job["job_id"], "PLANNED")
        self.create_application(applied_job["job_id"], "APPLIED")
        interview_application = self.create_application(interview_job["job_id"], "APPLIED")
        moved = self.client.post(f"/api/applications/{interview_application['application_id']}/transitions", json={
            "status": "INTERVIEW", "version": interview_application["version"],
            "next_action": "技术一面", "notes": "", "command_id": "phase3:status:interview",
        })
        self.assertEqual(moved.status_code, 200, moved.text)
        scheduled = self.client.post(f"/api/applications/{interview_application['application_id']}/interviews", json={
            "title": "近期技术面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": self.utc_time(days=2),
        })
        self.assertEqual(scheduled.status_code, 201, scheduled.text)
        overdue = self.client.post("/api/tasks", json={
            "title": "已逾期待办", "task_type": "FOLLOW_UP", "status": "TODO", "priority": "P1", "due_at": self.utc_time(days=-1),
        })
        self.assertEqual(overdue.status_code, 201, overdue.text)
        overview = self.client.get("/api/workbench").json()
        funnel = {item["stage"]: item["count"] for item in overview["application_funnel"]}
        self.assertEqual(funnel, {"PLANNED": 1, "APPLIED": 1, "ASSESSMENT": 0, "INTERVIEW": 1, "OFFER": 0})
        self.assertEqual(overview["counts"]["overdue_tasks"], 1)
        self.assertEqual(overview["overdue_tasks"][0]["title"], "已逾期待办")
        self.assertEqual(overview["recent_interviews"][0]["title"], "近期技术面")

    def test_job_comparison_is_deterministic_validated_and_isolated(self) -> None:
        first = self.create_job(company_name="Compare A", required_skills=["Python", "Django"])
        second = self.create_job(company_name="Compare B", required_skills=["Python", "FastAPI"])
        payload = {"job_ids": [first["job_id"], second["job_id"]]}
        one = self.client.post("/api/jobs/compare", json=payload)
        two = self.client.post("/api/jobs/compare", json=payload)
        self.assertEqual(one.status_code, 200, one.text)
        self.assertEqual(one.json(), two.json())
        items = one.json()["comparison"]["items"]
        self.assertEqual([item["job"]["company_name"] for item in items], ["Compare A", "Compare B"])
        self.assertEqual(items[0]["match"]["required_coverage"]["ratio"], 0.5)
        self.assertEqual(items[1]["match"]["required_coverage"]["ratio"], 1.0)
        self.assertEqual(self.client.post("/api/jobs/compare", json={"job_ids": [first["job_id"]]}).status_code, 400)
        admin = TestClient(self.app)
        admin.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        admin.post("/api/auth/users", json={"username": "phase3other", "password": "phase3other", "role": "user"})
        other = TestClient(self.app)
        other.post("/api/auth/login", json={"username": "phase3other", "password": "phase3other"})
        isolated = other.post("/api/jobs/compare", json=payload)
        self.assertEqual(isolated.status_code, 404)
        admin.close()
        other.close()

    def test_v52_has_no_live_source_refresh_endpoint(self) -> None:
        job = self.create_job(source_type="COMPANY_CAREER", source_name="企业招聘官网")
        response = self.client.post(f"/api/jobs/{job['job_id']}/source-refresh")
        self.assertIn(response.status_code, {404, 405})
        self.assertEqual(self.client.get(f"/api/jobs/{job['job_id']}").json()["job"]["title"], job["title"])

    def test_frontend_keeps_phase3_features_after_phase5_agentops_addition(self) -> None:
        src = Path(__file__).resolve().parents[1] / "frontend" / "src"
        sidebar = (src / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
        self.assertEqual(sidebar.count("{ id: '"), 7)
        workbench = (src / "views" / "WorkbenchView.vue").read_text(encoding="utf-8")
        for term in ("task-suggestions", "application_funnel", "overdue_tasks", "recent_interviews"):
            self.assertIn(term, workbench)
        jobs = (src / "views" / "JobCenterView.vue").read_text(encoding="utf-8")
        for term in ("/api/jobs/compare", "saveJob", "optimizeResume"):
            self.assertIn(term, jobs)
        self.assertNotIn("source-refresh", jobs)
        self.assertTrue(any(path.name == "CareerAgentView.vue" for path in src.rglob("*.vue")))


if __name__ == "__main__":
    unittest.main()
