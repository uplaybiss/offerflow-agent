from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from api.main import create_app


def expect(response, status=200):
    if response.status_code != status:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.status_code} {response.text}")
    return response.json() if response.content else None


def run() -> None:
    with tempfile.TemporaryDirectory() as folder:
        db_path = str(Path(folder) / "acceptance.db")
        app = create_app(db_path=db_path, session_secret="acceptance-secret")
        client = TestClient(app)
        checks: list[str] = []

        expect(client.post("/api/auth/login", json={"username": "demo", "password": "demo"}))
        candidate = expect(client.get("/api/candidate"))["candidate"]
        candidate = expect(client.put("/api/candidate", json={
            "version": candidate["version"], "full_name": "Phase 1 求职者", "email": "candidate@example.com", "phone": "",
            "graduation_year": "2027", "degree": "MSc Computer Science", "target_roles": ["AI 应用工程师"],
            "preferred_cities": ["上海", "深圳"], "excluded_companies": [], "preferences": {"employment": "full-time"},
            "skills": ["Python", "FastAPI", "Vue 3"], "current_resume_text": "Phase 1 当前简历", "current_resume_parsed": {"education": [], "projects": []}, "current_resume_filename": "resume-phase1.txt",
        }))["candidate"]
        checks.append("候选人档案与当前简历保存")

        job_payload = {
            "company_name": "验收科技", "title": "AI 应用开发工程师", "location": "上海", "deadline": "2026-12-31",
            "description_text": "手工粘贴的真实 JD 示例", "required_skills": ["Python"], "preferred_skills": ["FastAPI"],
            "is_favorite": True, "source_type": "COMPANY_CAREER", "source_name": "验收科技招聘官网",
            "source_url": "https://careers.example.test/job/OF-001", "external_job_id": "OF-001", "company_career_url": "https://careers.example.test",
        }
        job = expect(client.post("/api/jobs", json=job_payload), 201)["job"]
        duplicate = client.post("/api/jobs", json=job_payload)
        if duplicate.status_code != 409:
            raise RuntimeError("重复岗位未被阻止")
        checks.append("岗位录入、收藏、来源预留与重复拦截")

        create_body = {"job_id": job["job_id"], "status": "PLANNED", "next_action": "完善材料", "notes": "验收创建", "command_id": "accept:create-001"}
        application = expect(client.post("/api/applications", json=create_body), 201)["application"]
        replay = expect(client.post("/api/applications", json=create_body), 201)
        if not replay["idempotent_replay"]:
            raise RuntimeError("幂等重放未命中")
        transition_body = {"status": "APPLIED", "next_action": "等待测评", "notes": "已从官网投递", "version": application["version"], "command_id": "accept:status-001"}
        application = expect(client.post(f"/api/applications/{application['application_id']}/transitions", json=transition_body))["application"]
        if len(application["events"]) != 2:
            raise RuntimeError("事件时间线不完整")
        stale = client.post(f"/api/applications/{application['application_id']}/transitions", json={"status": "INTERVIEW", "version": 1, "command_id": "accept:stale-001"})
        if stale.status_code != 409:
            raise RuntimeError("CAS 未拦截旧版本")
        checks.append("投递状态迁移、Event、幂等与 version CAS")

        interview = expect(client.post(f"/api/applications/{application['application_id']}/interviews", json={"title": "技术一面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": "2026-09-20T10:00:00", "notes": "复习项目"}), 201)["interview"]
        expect(client.post("/api/tasks", json={"title": "准备技术一面", "description": "复盘项目状态机", "task_type": "INTERVIEW", "status": "TODO", "priority": "P1", "due_at": "2026-09-19T18:00:00", "application_id": application["application_id"], "interview_round_id": interview["round_id"]}), 201)
        overview = expect(client.get("/api/workbench"))
        if overview["counts"]["open_tasks"] != 1 or overview["counts"]["upcoming_interviews"] != 1:
            raise RuntimeError("工作台聚合结果不正确")
        checks.append("面试、待办与工作台聚合")

        admin = TestClient(app)
        expect(admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}))
        expect(admin.post("/api/auth/users", json={"username": "phase1user", "password": "phase1pass", "role": "user"}), 201)
        second = TestClient(app)
        expect(second.post("/api/auth/login", json={"username": "phase1user", "password": "phase1pass"}))
        if expect(second.get("/api/jobs"))["items"]:
            raise RuntimeError("用户数据未隔离")
        checks.append("多用户数据隔离")

        restarted = TestClient(create_app(db_path=db_path, session_secret="acceptance-secret"))
        expect(restarted.post("/api/auth/login", json={"username": "demo", "password": "demo"}))
        if len(expect(restarted.get("/api/jobs"))["items"]) != 1:
            raise RuntimeError("重启后数据未恢复")
        checks.append("SQLite WAL 持久化与重启恢复")

        print("PHASE 1 ACCEPTANCE: PASS")
        for index, item in enumerate(checks, 1):
            print(f"  {index}. PASS - {item}")
        print(f"  tables={len(app.state.services.database.table_names())}, timezone={overview['timezone']}, app_events={len(application['events'])}")


if __name__ == "__main__":
    run()
