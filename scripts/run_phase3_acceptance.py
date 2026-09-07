from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from api.main import create_app
from core.time import configured_timezone


def expect(response, status: int = 200) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.status_code} {response.text}")
    return response.json()


def utc_after(*, days: int = 0, hours: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days, hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")


def run() -> None:
    with tempfile.TemporaryDirectory() as folder:
        app = create_app(db_path=str(Path(folder) / "phase3-acceptance.db"), session_secret="phase3-acceptance")
        with TestClient(app) as client:
            checks: list[str] = []
            expect(client.post("/api/auth/login", json={"username": "demo", "password": "demo"}))
            candidate = expect(client.get("/api/candidate"))["candidate"]
            expect(client.put("/api/candidate", json={
                **candidate, "version": candidate["version"], "graduation_year": "2027", "degree": "MSc",
                "preferred_cities": ["上海"], "skills": ["Python", "FastAPI", "Vue 3"],
            }))

            deadline = (datetime.now(configured_timezone()).date() + timedelta(days=10)).isoformat()
            job = expect(client.post("/api/jobs", json={
                "company_name": "Phase 3 验收科技", "title": "AI 应用工程师", "location": "上海",
                "employment_type": "全职", "recruitment_cycle": "2027 届秋招", "graduation_year": "2027",
                "deadline": deadline, "description_text": "要求 Python 与 FastAPI，Vue 3 优先",
                "required_skills": ["Python", "FastAPI"], "preferred_skills": ["Vue 3"], "is_favorite": True,
                "source_type": "JD_PASTE", "source_name": "用户粘贴的合成 JD",
                "external_job_id": "P3-ACCEPT-1",
            }), 201)["job"]
            application = expect(client.post("/api/applications", json={
                "job_id": job["job_id"], "status": "PLANNED", "next_action": "准备投递", "notes": "",
                "command_id": "phase3:accept:create",
            }), 201)["application"]
            expect(client.post(f"/api/applications/{application['application_id']}/interviews", json={
                "title": "在线测评", "round_type": "ASSESSMENT", "status": "SCHEDULED", "scheduled_at": utc_after(days=3),
            }), 201)
            expect(client.post(f"/api/applications/{application['application_id']}/interviews", json={
                "title": "技术一面", "round_type": "TECHNICAL", "status": "SCHEDULED", "scheduled_at": utc_after(days=5),
            }), 201)

            suggestions = expect(client.get("/api/task-suggestions"))["items"]
            if {item["source"]["type"] for item in suggestions} != {"JOB_DEADLINE", "ASSESSMENT_TIME", "INTERVIEW_TIME"}:
                raise RuntimeError("建议任务没有覆盖岗位截止、测评和面试时间")
            if expect(client.get("/api/tasks"))["items"]:
                raise RuntimeError("未确认建议不应写入待办")
            checks.append("三类建议均可追溯，确认前不落库")

            first_suggestion = suggestions[0]
            accepted = expect(client.post(f"/api/task-suggestions/{first_suggestion['suggestion_key']}/accept"), 201)
            replay = expect(client.post(f"/api/task-suggestions/{first_suggestion['suggestion_key']}/accept"), 201)
            if accepted["idempotent_replay"] or not replay["idempotent_replay"]:
                raise RuntimeError("建议任务幂等保留失败")
            if len(expect(client.get("/api/tasks"))["items"]) != 1:
                raise RuntimeError("重复确认产生了重复待办")
            checks.append("建议任务重复确认幂等且只有一条正式待办")

            retained = accepted["task"]
            edited = expect(client.patch(f"/api/tasks/{retained['task_id']}", json={
                **retained, "version": retained["version"], "title": "用户手工调整后的任务", "priority": "P3",
            }))["task"]
            if edited["title"] != "用户手工调整后的任务" or edited["origin"] != "SUGGESTED":
                raise RuntimeError("建议保留后的待办不可编辑或丢失来源")
            checks.append("建议保留后可手工编辑且来源仍可追溯")

            expect(client.post("/api/tasks", json={
                "title": "逾期跟进", "task_type": "FOLLOW_UP", "status": "TODO", "priority": "P1", "due_at": utc_after(days=-1),
            }), 201)
            overview = expect(client.get("/api/workbench"))
            if overview["counts"]["overdue_tasks"] != 1 or len(overview["recent_interviews"]) != 2:
                raise RuntimeError("工作台逾期待办或近期面试聚合错误")
            if not any(item["stage"] == "PLANNED" and item["count"] == 1 for item in overview["application_funnel"]):
                raise RuntimeError("投递漏斗聚合错误")
            checks.append("投递漏斗、近期面试和逾期待办视图正确")

            second = expect(client.post("/api/jobs", json={
                "company_name": "Phase 3 对比公司", "title": "Python 后端", "location": "深圳",
                "deadline": deadline, "required_skills": ["Python", "Django"], "preferred_skills": [],
                "source_type": "MANUAL", "external_job_id": "P3-ACCEPT-2",
            }), 201)["job"]
            comparison = expect(client.post("/api/jobs/compare", json={"job_ids": [job["job_id"], second["job_id"]]}))["comparison"]
            if len(comparison["items"]) != 2 or not comparison["deterministic"]:
                raise RuntimeError("岗位对比结果不完整")
            checks.append("岗位对比展示岗位事实、确定性匹配和技能缺口")

            before = expect(client.get(f"/api/jobs/{job['job_id']}"))["job"]
            refresh = client.post(f"/api/jobs/{job['job_id']}/source-refresh")
            after = expect(client.get(f"/api/jobs/{job['job_id']}"))["job"]
            if refresh.status_code not in {404, 405} or before != after:
                raise RuntimeError("v5.2 不应保留岗位来源刷新入口或改变岗位")
            checks.append("在线岗位刷新入口已删除，已保存岗位保持不变")

            updated = expect(client.patch(f"/api/jobs/{job['job_id']}", json={
                "version": job["version"], "title": "用户手工修正后的岗位名",
            }))["job"]
            if updated["title"] != "用户手工修正后的岗位名":
                raise RuntimeError("单条岗位手工更新失败")
            checks.append("单条岗位始终可由用户手工更新")

            if len(app.state.services.database.table_names()) != 12:
                raise RuntimeError("v5.2 数据表数量异常")
            checks.append("Phase 3 功能在 v5.2 新增简历版本与会话表后回归通过")

            print("PHASE 3 ACCEPTANCE: PASS")
            for index, item in enumerate(checks, 1):
                print(f"  {index}. PASS - {item}")
            print(f"  suggestions={len(suggestions)}, tasks={len(expect(client.get('/api/tasks'))['items'])}, tables=12")


if __name__ == "__main__":
    run()
