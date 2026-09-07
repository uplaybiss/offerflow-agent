from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from api.main import create_app
from core.errors import ConflictError
from core.time import normalize_utc_datetime, timezone_name


class Phase1TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "test.db")
        self.app = create_app(db_path=self.db_path, session_secret="test-secret")
        self.client = TestClient(self.app)
        login = self.client.post("/api/auth/login", json={"username": "demo", "password": "demo"})
        self.assertEqual(login.status_code, 200)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def create_job(self, **changes):
        payload = {
            "company_name": "Example Tech",
            "title": "AI 应用开发工程师",
            "location": "上海",
            "employment_type": "全职",
            "recruitment_cycle": "2027 届秋招",
            "graduation_year": "2027",
            "deadline": "2027-01-31",
            "description_text": "负责 Python 与 FastAPI 服务开发",
            "required_skills": ["Python", "FastAPI"],
            "preferred_skills": ["Vue 3"],
            "source_type": "JD_PASTE",
            "source_name": "企业招聘页",
            "source_url": "https://example.test/jobs/1",
            "external_job_id": "EXT-1",
            "company_career_url": "https://example.test/careers",
            "is_favorite": True,
        }
        payload.update(changes)
        response = self.client.post("/api/jobs", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["job"]

    def create_application(self, job_id: str, command_id: str = "create:test-001"):
        response = self.client.post(
            "/api/applications",
            json={"job_id": job_id, "status": "PLANNED", "next_action": "准备材料", "notes": "", "command_id": command_id},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_schema_has_phase1_tables_plus_phase4_agent_state_and_wal(self):
        expected = {"users", "candidate_profiles", "jobs", "applications", "application_events", "interview_rounds", "job_search_tasks", "agent_memories", "pending_actions", "resume_versions", "chat_threads", "chat_messages"}
        self.assertEqual(set(self.app.state.services.database.table_names()), expected)
        connection = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 0)
        finally:
            connection.close()
        with self.app.state.services.database.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_display_timezone_is_configurable_while_storage_is_utc(self):
        previous = os.environ.get("APP_TIMEZONE")
        os.environ["APP_TIMEZONE"] = "Asia/Tokyo"
        try:
            self.assertEqual(timezone_name(), "Asia/Tokyo")
            self.assertEqual(normalize_utc_datetime("2026-09-06T09:00:00"), "2026-09-06T00:00:00.000Z")
            self.assertEqual(self.client.get("/api/health").json()["timezone"], "Asia/Tokyo")
        finally:
            if previous is None:
                os.environ.pop("APP_TIMEZONE", None)
            else:
                os.environ["APP_TIMEZONE"] = previous

    def test_auth_and_candidate_profile_version_cas(self):
        candidate = self.client.get("/api/candidate").json()["candidate"]
        payload = {
            "version": candidate["version"], "full_name": "王同学", "email": "wj@example.com", "phone": "13800000000",
            "graduation_year": "2027", "degree": "MSc", "target_roles": ["AI应用"], "preferred_cities": ["上海"],
            "excluded_companies": [], "preferences": {"work_type": "full-time"}, "skills": ["Python", "FastAPI"],
            "current_resume_text": "王同学 Python FastAPI", "current_resume_parsed": {"skills": ["Python"]}, "current_resume_filename": "resume.txt",
        }
        updated = self.client.put("/api/candidate", json=payload)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["candidate"]["version"], 2)
        self.assertEqual(len(updated.json()["candidate"]["current_resume_sha256"]), 64)
        stale = self.client.put("/api/candidate", json=payload)
        self.assertEqual(stale.status_code, 409)

    def test_job_source_favorite_duplicate_and_effective_expiration(self):
        job = self.create_job(deadline="2020-01-01")
        self.assertEqual(job["effective_status"], "EXPIRED")
        self.assertEqual(job["status"], "ACTIVE")
        self.assertTrue(job["is_favorite"])
        duplicate = self.client.post("/api/jobs", json={
            "company_name": job["company_name"], "title": job["title"], "location": job["location"],
            "deadline": "2020-01-01", "description_text": job["description_text"], "required_skills": job["required_skills"],
            "preferred_skills": job["preferred_skills"], "source_type": job["source_type"], "source_name": job["source_name"],
            "source_url": job["source_url"], "external_job_id": job["external_job_id"], "company_career_url": job["company_career_url"],
        })
        self.assertEqual(duplicate.status_code, 409)
        toggled = self.client.patch(f"/api/jobs/{job['job_id']}", json={"version": job["version"], "is_favorite": False})
        self.assertEqual(toggled.status_code, 200)
        self.assertFalse(toggled.json()["job"]["is_favorite"])

    def test_expired_filter_includes_explicit_and_effective_expiration(self):
        effective = self.create_job(deadline="2020-01-01")
        explicit = self.create_job(
            company_name="Explicit Expired", title="测试开发", external_job_id="EXT-2",
            source_url="https://example.test/jobs/2", status="EXPIRED", deadline="2030-01-01",
        )
        active = self.create_job(
            company_name="Still Active", title="后端开发", external_job_id="EXT-3",
            source_url="https://example.test/jobs/3", deadline="2030-01-01",
        )
        result = self.client.get("/api/jobs?status=EXPIRED")
        self.assertEqual(result.status_code, 200, result.text)
        ids = {item["job_id"] for item in result.json()["items"]}
        self.assertEqual(ids, {effective["job_id"], explicit["job_id"]})
        self.assertNotIn(active["job_id"], ids)

    def test_application_create_rejects_all_non_initial_states(self):
        forbidden = ["ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"]
        for index, status in enumerate(forbidden, 1):
            job = self.create_job(
                company_name=f"Forbidden {index}", title=f"Role {index}",
                external_job_id=f"FORBID-{index}", source_url=f"https://example.test/forbid/{index}",
            )
            response = self.client.post("/api/applications", json={
                "job_id": job["job_id"], "status": status, "next_action": "", "notes": "",
                "command_id": f"create:forbidden-{index}",
            })
            self.assertEqual(response.status_code, 400, f"{status} unexpectedly accepted: {response.text}")
        allowed_job = self.create_job(
            company_name="Applied Allowed", title="Role Allowed", external_job_id="ALLOW-APPLIED",
            source_url="https://example.test/allowed/applied",
        )
        allowed = self.client.post("/api/applications", json={
            "job_id": allowed_job["job_id"], "status": "APPLIED", "next_action": "等待反馈",
            "notes": "历史手工录入", "command_id": "create:allowed-applied",
        })
        self.assertEqual(allowed.status_code, 201, allowed.text)

    def test_application_event_idempotency_state_machine_and_cas(self):
        job = self.create_job()
        created = self.create_application(job["job_id"])
        app = created["application"]
        self.assertFalse(created["idempotent_replay"])
        replay = self.create_application(job["job_id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(len(app["events"]), 1)
        body = {"status": "APPLIED", "next_action": "等待测评", "notes": "9 月 6 日投递", "version": 1, "command_id": "status:test-001"}
        moved = self.client.post(f"/api/applications/{app['application_id']}/transitions", json=body)
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["application"]["version"], 2)
        self.assertEqual(len(moved.json()["application"]["events"]), 2)
        self.assertTrue(self.client.post(f"/api/applications/{app['application_id']}/transitions", json=body).json()["idempotent_replay"])
        invalid = self.client.post(f"/api/applications/{app['application_id']}/transitions", json={"status": "PLANNED", "version": 2, "command_id": "status:test-invalid"})
        self.assertEqual(invalid.status_code, 409)
        stale = self.client.post(f"/api/applications/{app['application_id']}/transitions", json={"status": "INTERVIEW", "version": 1, "command_id": "status:test-stale"})
        self.assertEqual(stale.status_code, 409)

    def test_application_concurrent_version_cas_has_one_winner(self):
        job = self.create_job()
        app = self.create_application(job["job_id"])["application"]
        candidate_id = self.client.get("/api/candidate").json()["candidate"]["candidate_id"]
        service = self.app.state.services.applications
        def move(target: str):
            try:
                return service.transition(candidate_id, app["application_id"], "demo", {"status": target, "version": 1, "command_id": f"race:{target.lower()}-0001"})["application"]["status"]
            except ConflictError:
                return "CONFLICT"
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(move, ["APPLIED", "WITHDRAWN"]))
        self.assertEqual(results.count("CONFLICT"), 1)
        self.assertEqual(len([item for item in results if item != "CONFLICT"]), 1)

    def test_interviews_tasks_workbench_and_link_validation(self):
        job = self.create_job()
        app = self.create_application(job["job_id"])["application"]
        interview = self.client.post(f"/api/applications/{app['application_id']}/interviews", json={"title": "一面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": "2026-09-10T10:00:00", "notes": "准备项目"})
        self.assertEqual(interview.status_code, 201, interview.text)
        round_item = interview.json()["interview"]
        self.assertTrue(round_item["scheduled_at"].endswith("Z"))
        task = self.client.post("/api/tasks", json={"title": "复习状态机", "task_type": "INTERVIEW", "status": "TODO", "priority": "P1", "due_at": "2026-09-09T12:00:00", "application_id": app["application_id"], "interview_round_id": round_item["round_id"]})
        self.assertEqual(task.status_code, 201, task.text)
        task_item = task.json()["task"]
        self.assertTrue(task_item["due_at"].endswith("Z"))
        done = self.client.patch(f"/api/tasks/{task_item['task_id']}", json={**task_item, "status": "DONE", "version": task_item["version"]})
        self.assertEqual(done.status_code, 200, done.text)
        workbench = self.client.get("/api/workbench")
        self.assertEqual(workbench.status_code, 200)
        self.assertEqual(workbench.json()["counts"]["upcoming_interviews"], 1)
        self.assertEqual(workbench.json()["timezone"], os.getenv("APP_TIMEZONE", "Asia/Shanghai"))

    def test_task_rejects_cross_chain_job_application_and_interview_links(self):
        job_one = self.create_job(company_name="Chain One", title="Role One", external_job_id="CHAIN-1", source_url="https://example.test/chain/1")
        job_two = self.create_job(company_name="Chain Two", title="Role Two", external_job_id="CHAIN-2", source_url="https://example.test/chain/2")
        app_one = self.create_application(job_one["job_id"], "create:chain-app-1")["application"]
        app_two = self.create_application(job_two["job_id"], "create:chain-app-2")["application"]
        round_one = self.client.post(f"/api/applications/{app_one['application_id']}/interviews", json={"title": "One", "round_type": "TECHNICAL", "status": "PLANNED"}).json()["interview"]
        round_two = self.client.post(f"/api/applications/{app_two['application_id']}/interviews", json={"title": "Two", "round_type": "HR", "status": "PLANNED"}).json()["interview"]
        base = {"title": "不一致待办", "task_type": "INTERVIEW", "status": "TODO", "priority": "P2"}
        inconsistent = [
            {"job_id": job_one["job_id"], "application_id": app_two["application_id"]},
            {"application_id": app_one["application_id"], "interview_round_id": round_two["round_id"]},
            {"job_id": job_one["job_id"], "interview_round_id": round_two["round_id"]},
            {"job_id": job_one["job_id"], "application_id": app_one["application_id"], "interview_round_id": round_two["round_id"]},
        ]
        for links in inconsistent:
            response = self.client.post("/api/tasks", json={**base, **links})
            self.assertEqual(response.status_code, 400, response.text)
        valid = self.client.post("/api/tasks", json={
            **base, "job_id": job_one["job_id"], "application_id": app_one["application_id"],
            "interview_round_id": round_one["round_id"],
        })
        self.assertEqual(valid.status_code, 201, valid.text)
        valid_task = valid.json()["task"]
        inconsistent_update = self.client.patch(f"/api/tasks/{valid_task['task_id']}", json={
            **valid_task, "version": valid_task["version"], "job_id": job_two["job_id"],
        })
        self.assertEqual(inconsistent_update.status_code, 400, inconsistent_update.text)

    def test_task_patch_supports_edit_and_cancel(self):
        job = self.create_job()
        app = self.create_application(job["job_id"])["application"]
        created = self.client.post("/api/tasks", json={
            "title": "准备简历", "description": "第一版", "task_type": "MATERIAL", "status": "TODO",
            "priority": "P2", "due_at": "2026-09-10T18:00:00", "job_id": job["job_id"],
            "application_id": app["application_id"],
        }).json()["task"]
        edited_response = self.client.patch(f"/api/tasks/{created['task_id']}", json={
            **created, "version": created["version"], "title": "准备定制简历", "description": "补充项目证据",
            "priority": "P1", "status": "IN_PROGRESS", "due_at": "2026-09-11T18:00:00",
        })
        self.assertEqual(edited_response.status_code, 200, edited_response.text)
        edited = edited_response.json()["task"]
        self.assertEqual((edited["title"], edited["priority"], edited["status"]), ("准备定制简历", "P1", "IN_PROGRESS"))
        cancelled = self.client.patch(f"/api/tasks/{created['task_id']}", json={**edited, "version": edited["version"], "status": "CANCELLED"})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["task"]["status"], "CANCELLED")

    def test_interview_patch_supports_reschedule_complete_cancel_and_result(self):
        job = self.create_job()
        app = self.create_application(job["job_id"])["application"]
        first = self.client.post(f"/api/applications/{app['application_id']}/interviews", json={
            "title": "技术一面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": "2026-09-10T10:00:00",
        }).json()["interview"]
        completed_response = self.client.patch(f"/api/interviews/{first['round_id']}", json={
            "version": first["version"], "title": "技术一面（改期）", "round_type": "TECHNICAL",
            "status": "COMPLETED", "scheduled_at": "2026-09-12T14:00:00", "notes": "已完成",
            "result": "通过，进入二面",
        })
        self.assertEqual(completed_response.status_code, 200, completed_response.text)
        completed = completed_response.json()["interview"]
        self.assertEqual((completed["status"], completed["result"]), ("COMPLETED", "通过，进入二面"))
        self.assertTrue(completed["completed_at"].endswith("Z"))
        second = self.client.post(f"/api/applications/{app['application_id']}/interviews", json={
            "title": "HR 面", "round_type": "HR", "status": "SCHEDULED", "scheduled_at": "2026-09-15T10:00:00",
        }).json()["interview"]
        cancelled = self.client.patch(f"/api/interviews/{second['round_id']}", json={"version": second["version"], "status": "CANCELLED"})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["interview"]["status"], "CANCELLED")

    def test_candidate_data_isolation(self):
        self.create_job()
        admin = TestClient(self.app)
        self.assertEqual(admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code, 200)
        self.assertEqual(admin.post("/api/auth/users", json={"username": "alice", "password": "alice", "role": "user"}).status_code, 201)
        alice = TestClient(self.app)
        self.assertEqual(alice.post("/api/auth/login", json={"username": "alice", "password": "alice"}).status_code, 200)
        self.assertEqual(alice.get("/api/jobs").json()["items"], [])
        admin.close(); alice.close()

    def test_frontend_keeps_phase1_views_after_phase5_agentops_addition(self):
        src = Path(__file__).resolve().parents[1] / "frontend" / "src"
        sidebar = (src / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
        for label in ("今日工作台", "岗位中心", "简历中心", "投递进度", "个人中心"):
            self.assertIn(label, sidebar)
        self.assertEqual(sidebar.count("{ id: '"), 7)
        self.assertTrue(any(path.name == "CareerAgentView.vue" for path in src.rglob("*.vue")))

    def test_frontend_phase11_maintenance_and_valid_job_row_contracts(self):
        src = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views"
        jobs = (src / "JobCenterView.vue").read_text(encoding="utf-8")
        for field in ("form.employment_type", "form.recruitment_cycle", "form.graduation_year", "selected.employment_type", "selected.recruitment_cycle", "selected.graduation_year"):
            self.assertIn(field, jobs)
        self.assertNotIn('<button v-for="item in jobs"', jobs)
        self.assertIn('class="job-row"', jobs)
        self.assertIn('class="job-select"', jobs)
        class ButtonNestingParser(HTMLParser):
            def __init__(self):
                super().__init__(); self.stack = []; self.nested = False
            def handle_starttag(self, tag, attrs):
                if tag == "button" and "button" in self.stack:
                    self.nested = True
                self.stack.append(tag)
            def handle_startendtag(self, tag, attrs):
                if tag == "button" and "button" in self.stack:
                    self.nested = True
            def handle_endtag(self, tag):
                if tag in self.stack:
                    reverse_index = self.stack[::-1].index(tag)
                    del self.stack[len(self.stack) - reverse_index - 1:]
        parser = ButtonNestingParser()
        parser.feed(jobs.split("<template>", 1)[1])
        self.assertFalse(parser.nested)
        tasks = (src / "WorkbenchView.vue").read_text(encoding="utf-8")
        self.assertIn("saveTask", tasks)
        self.assertIn("'CANCELLED'", tasks)
        interviews = (src / "ApplicationTrackerView.vue").read_text(encoding="utf-8")
        for contract in ("saveInterview", "changeInterviewStatus", "interviewEdit.result", "'COMPLETED'", "'CANCELLED'"):
            self.assertIn(contract, interviews)


if __name__ == "__main__":
    unittest.main()
