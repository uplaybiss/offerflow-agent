from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from api.main import create_app


class AcceptanceLlmClient:
    available = True
    provider = "acceptance-fake"
    model = "structured-v1"

    def complete_json(self, *, task: str, instructions: str, input_text: str) -> dict[str, Any]:
        if "简历" in task:
            return {
                "full_name": "Phase 2 求职者", "email": "candidate@example.test", "phone": "",
                "graduation_year": "2027", "degree": "MSc", "target_roles": ["AI 应用工程师"],
                "preferred_cities": ["上海"], "skills": ["Python", "FastAPI", "Vue 3"],
                "education": [], "experience": [], "projects": [], "certifications": [],
                "languages": ["英语"], "summary": "合成验收简历", "extraction_notes": [],
            }
        return {
            "company_name": "Phase 2 验收科技", "title": "AI 后端工程师", "location": "上海",
            "employment_type": "全职", "recruitment_cycle": "2027 届秋招", "graduation_year": "2027",
            "deadline": "2030-12-31", "required_skills": ["Python", "Django"],
            "preferred_skills": ["Vue 3"],
            "hard_conditions": {"required_degree": "硕士", "required_languages": ["英语"], "visa_sponsorship": None, "remote_supported": False},
            "extraction_notes": ["Django 为明确必需技能"],
        }

    def complete_text(self, *, task: str, instructions: str, facts: dict[str, Any]) -> str:
        return "硬条件满足；Python 已命中，Django 为具体缺口。该等级是启发式规则。"


def expect(response, status: int = 200) -> dict[str, Any]:
    if response.status_code != status:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.status_code} {response.text}")
    return response.json()


def run() -> None:
    with tempfile.TemporaryDirectory() as folder:
        app = create_app(
            db_path=str(Path(folder) / "phase2-acceptance.db"),
            session_secret="phase2-acceptance",
            llm_client=AcceptanceLlmClient(),
        )
        with TestClient(app) as client:
            checks: list[str] = []
            expect(client.post("/api/auth/login", json={"username": "demo", "password": "demo"}))
            original = expect(client.get("/api/candidate"))["candidate"]

            extraction = expect(client.post(
                "/api/parsing/resume/extract",
                files={"file": ("resume.txt", "Phase 2 求职者 Python FastAPI Vue 3".encode(), "text/plain")},
            ))
            if extraction["persisted"] or expect(client.get("/api/candidate"))["candidate"] != original:
                raise RuntimeError("简历文本提取不应写入正式档案")
            checks.append("TXT 简历提取在浏览器预览且不落库")

            resume = expect(client.post("/api/parsing/resume/preview", json={"text": extraction["extraction"]["text"]}))
            if resume["persisted"] or not resume["requires_confirmation"]:
                raise RuntimeError("简历结构化结果不是待确认预览")
            if expect(client.get("/api/candidate"))["candidate"] != original:
                raise RuntimeError("未确认简历预览覆盖了正式档案")
            preview = resume["preview"]
            saved = expect(client.put("/api/candidate", json={
                **preview, "version": original["version"], "excluded_companies": [],
                "preferences": {"accepted_employment_types": ["全职"], "languages": ["英语"]},
                "current_resume_text": extraction["extraction"]["text"],
                "current_resume_filename": extraction["extraction"]["filename"],
            }))["candidate"]
            if saved["skills"] != ["Python", "FastAPI", "Vue 3"]:
                raise RuntimeError("用户确认后的当前简历未正确保存")
            checks.append("简历结构化预览经显式确认后覆盖当前简历")

            jd = expect(client.post("/api/parsing/jd/preview", json={"text": "验收科技招聘 AI 后端，要求 Python、Django，上海，2027 届硕士。"}))
            if expect(client.get("/api/jobs"))["items"]:
                raise RuntimeError("未确认 JD 预览创建了岗位")
            job_preview = jd["preview"]
            job = expect(client.post("/api/jobs", json={
                **{name: job_preview[name] for name in (
                    "company_name", "title", "location", "employment_type", "recruitment_cycle",
                    "graduation_year", "deadline", "required_skills", "preferred_skills",
                )},
                "description_text": "验收科技招聘 AI 后端，要求 Python、Django，上海，2027 届硕士。",
                "source_type": "JD_PASTE", "source_name": "Phase 2 合成验收 JD", "is_favorite": True,
                "source_metadata": {"phase2_parsed": {"hard_conditions": job_preview["hard_conditions"], "parser": job_preview["parser"]}},
            }), 201)["job"]
            checks.append("JD 预览不落库，校对后显式创建岗位")

            first = expect(client.get(f"/api/jobs/{job['job_id']}/match"))["match"]
            second = expect(client.get(f"/api/jobs/{job['job_id']}/match"))["match"]
            if first != second or first["result_fingerprint"] != second["result_fingerprint"]:
                raise RuntimeError("同输入、同 heuristic 版本未产生相同结果")
            django = next(item for item in first["required_coverage"]["evidence"] if item["job_skill"] == "Django")
            if django["matched"] or first["required_coverage"]["ratio"] != 0.5:
                raise RuntimeError("FastAPI 被错误地等价为 Django")
            if "非录用概率" not in first["heuristic"]["disclaimer"]:
                raise RuntimeError("缺少 heuristic 非统计声明")
            checks.append("确定性匹配可复现，FastAPI 不命中 Django，展示逐项证据")

            explained = expect(client.post(f"/api/jobs/{job['job_id']}/match/explanation"))
            if not explained["facts_unchanged"] or explained["result_fingerprint"] != first["result_fingerprint"]:
                raise RuntimeError("模型解释改变了确定性事实")
            checks.append("模型仅解释确定性结果，不参与事实与等级决策")

            if len(app.state.services.database.table_names()) != 12:
                raise RuntimeError("v5.2 数据表数量异常")
            checks.append("Phase 2 功能在 v5.2 的 12 张业务表结构上回归通过")

            print("PHASE 2 ACCEPTANCE: PASS")
            for index, item in enumerate(checks, 1):
                print(f"  {index}. PASS - {item}")
            print(f"  grade={first['grade']}, required_coverage={first['required_coverage']['ratio']}, fingerprint={first['result_fingerprint'][:12]}...")


if __name__ == "__main__":
    run()
