from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from typing import Any

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from api.main import create_app
from core.errors import ExternalServiceError


class FakeLlmClient:
    available = True
    provider = "fake"
    model = "fake-structured-v1"

    def __init__(self) -> None:
        self.last_facts: dict[str, Any] | None = None

    def complete_json(self, *, task: str, instructions: str, input_text: str) -> dict[str, Any]:
        if "简历" in task:
            return {
                "full_name": "王同学",
                "email": "wj@example.com",
                "phone": "13800000000",
                "graduation_year": "2027",
                "degree": "MSc",
                "target_roles": ["AI 应用工程师"],
                "preferred_cities": ["上海"],
                "skills": ["Python", "FastAPI", "Vue 3"],
                "education": [{"school": "Example University", "degree": "MSc"}],
                "experience": [],
                "projects": [{"name": "OfferFlow", "skills": ["FastAPI"]}],
                "certifications": [],
                "languages": ["英语"],
                "summary": "Python AI 应用开发候选人",
                "extraction_notes": ["请校对毕业年份"],
            }
        return {
            "company_name": "Example Tech",
            "title": "AI 后端工程师",
            "location": "上海",
            "employment_type": "全职",
            "recruitment_cycle": "2027 届秋招",
            "graduation_year": "2027",
            "deadline": "2030-12-31",
            "required_skills": ["Python", "Django"],
            "preferred_skills": ["Vue 3"],
            "hard_conditions": {
                "required_degree": "硕士",
                "required_languages": ["英语"],
                "visa_sponsorship": None,
                "remote_supported": False,
            },
            "extraction_notes": ["Django 为明确必需技能"],
        }

    def complete_text(self, *, task: str, instructions: str, facts: dict[str, Any]) -> str:
        self.last_facts = facts
        return "硬条件满足；Python 已命中，Django 为明确缺口。该结果来自启发式规则。"


class UnavailableLlmClient:
    available = False
    provider = "dashscope"
    model = "qwen3-max"

    def complete_json(self, **_: Any) -> dict[str, Any]:
        raise ExternalServiceError("未配置 DASHSCOPE_API_KEY；仍可手工填写并保存")

    def complete_text(self, **_: Any) -> str:
        raise ExternalServiceError("未配置 DASHSCOPE_API_KEY；仍可手工填写并保存")


def text_pdf(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    stream = DecodedStreamObject()
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 50 250 Td ({safe_text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class Phase2TestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "phase2.db")
        self.llm = FakeLlmClient()
        self.app = create_app(db_path=self.db_path, session_secret="phase2-test", llm_client=self.llm)
        self.client = TestClient(self.app)
        login = self.client.post("/api/auth/login", json={"username": "demo", "password": "demo"})
        self.assertEqual(login.status_code, 200)

    def tearDown(self) -> None:
        self.client.close()
        self.temp.cleanup()

    def candidate(self) -> dict[str, Any]:
        return self.client.get("/api/candidate").json()["candidate"]

    def confirm_candidate(self, preview: dict[str, Any], resume_text: str = "Python FastAPI Vue 3") -> dict[str, Any]:
        current = self.candidate()
        payload = {
            **preview,
            "version": current["version"],
            "excluded_companies": current["excluded_companies"],
            "preferences": {"languages": ["英语"], "accepted_employment_types": ["全职"]},
            "current_resume_text": resume_text,
            "current_resume_filename": "resume.txt",
        }
        response = self.client.put("/api/candidate", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["candidate"]

    def create_job(self, **changes: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "company_name": "Example Tech",
            "title": "AI 后端工程师",
            "location": "上海",
            "employment_type": "全职",
            "recruitment_cycle": "2027 届秋招",
            "graduation_year": "2027",
            "deadline": "2030-12-31",
            "description_text": "Python 与 Django 开发",
            "required_skills": ["Python", "Django"],
            "preferred_skills": ["Vue 3"],
            "source_type": "JD_PASTE",
            "source_name": "测试 JD",
            "source_url": "https://example.test/phase2",
            "external_job_id": "PHASE2-1",
            "source_metadata": {
                "phase2_parsed": {
                    "hard_conditions": {
                        "required_degree": "硕士",
                        "required_languages": ["英语"],
                        "remote_supported": False,
                        "visa_sponsorship": None,
                    },
                    "critical_required_skills": [],
                }
            },
        }
        payload.update(changes)
        response = self.client.post("/api/jobs", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["job"]

    def test_resume_txt_and_pdf_extraction_are_local_and_do_not_persist(self) -> None:
        before = self.candidate()
        txt = self.client.post(
            "/api/parsing/resume/extract",
            files={"file": ("resume.txt", "王同学 Python FastAPI".encode(), "text/plain")},
        )
        self.assertEqual(txt.status_code, 200, txt.text)
        self.assertEqual(txt.json()["extraction"]["text"], "王同学 Python FastAPI")
        self.assertFalse(txt.json()["persisted"])
        pdf = self.client.post(
            "/api/parsing/resume/extract",
            files={"file": ("resume.pdf", text_pdf("Python FastAPI Resume"), "application/pdf")},
        )
        self.assertEqual(pdf.status_code, 200, pdf.text)
        self.assertIn("Python FastAPI Resume", pdf.json()["extraction"]["text"])
        self.assertEqual(self.candidate(), before)

    def test_resume_extraction_rejects_invalid_empty_and_scanned_files(self) -> None:
        invalid = self.client.post(
            "/api/parsing/resume/extract", files={"file": ("resume.docx", b"not docx", "application/octet-stream")}
        )
        self.assertEqual(invalid.status_code, 400)
        empty = self.client.post(
            "/api/parsing/resume/extract", files={"file": ("resume.txt", b"", "text/plain")}
        )
        self.assertEqual(empty.status_code, 400)
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        output = BytesIO()
        writer.write(output)
        scanned = self.client.post(
            "/api/parsing/resume/extract", files={"file": ("scan.pdf", output.getvalue(), "application/pdf")}
        )
        self.assertEqual(scanned.status_code, 400)
        self.assertIn("OCR", scanned.text)

    def test_resume_preview_requires_explicit_candidate_overwrite(self) -> None:
        before = self.candidate()
        response = self.client.post("/api/parsing/resume/preview", json={"text": "王同学，2027 MSc，Python FastAPI"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["persisted"])
        self.assertTrue(body["requires_confirmation"])
        self.assertEqual(self.candidate(), before)
        saved = self.confirm_candidate(body["preview"])
        self.assertEqual(saved["full_name"], "王同学")
        self.assertEqual(saved["skills"], ["Python", "FastAPI", "Vue 3"])
        self.assertEqual(saved["current_resume_parsed"]["parser"]["schema"], "resume_preview_v1")

    def test_jd_preview_creates_nothing_until_explicit_job_save(self) -> None:
        response = self.client.post("/api/parsing/jd/preview", json={"text": "Example Tech 招聘 AI 后端，要求 Python、Django"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["persisted"])
        self.assertEqual(self.client.get("/api/jobs").json()["items"], [])
        preview = body["preview"]
        job = self.create_job(
            company_name=preview["company_name"],
            title=preview["title"],
            location=preview["location"],
            employment_type=preview["employment_type"],
            recruitment_cycle=preview["recruitment_cycle"],
            graduation_year=preview["graduation_year"],
            deadline=preview["deadline"],
            required_skills=preview["required_skills"],
            preferred_skills=preview["preferred_skills"],
            source_metadata={"phase2_parsed": {"hard_conditions": preview["hard_conditions"]}},
        )
        self.assertEqual(job["source_metadata"]["phase2_parsed"]["hard_conditions"]["required_degree"], "硕士")

    def test_matching_is_deterministic_and_fastapi_never_equals_django(self) -> None:
        preview = self.client.post("/api/parsing/resume/preview", json={"text": "Python FastAPI Vue 3"}).json()["preview"]
        self.confirm_candidate(preview)
        job = self.create_job()
        first = self.client.get(f"/api/jobs/{job['job_id']}/match")
        second = self.client.get(f"/api/jobs/{job['job_id']}/match")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        match = first.json()["match"]
        self.assertEqual(match["required_coverage"]["ratio"], 0.5)
        django = next(item for item in match["required_coverage"]["evidence"] if item["job_skill"] == "Django")
        self.assertFalse(django["matched"])
        self.assertIsNone(django["candidate_skill"])
        self.assertEqual(django["canonical_skill"], "django")
        self.assertEqual(django["skill_category"], "backend_framework")
        self.assertEqual(len(match["result_fingerprint"]), 64)

    def test_hard_condition_failure_overrides_skill_coverage(self) -> None:
        current = self.candidate()
        response = self.client.put(
            "/api/candidate",
            json={
                **current,
                "version": current["version"],
                "graduation_year": "2027",
                "degree": "MSc",
                "preferred_cities": ["上海"],
                "skills": ["Python", "Django", "Vue 3"],
                "preferences": {"languages": ["英语"], "accepted_employment_types": ["全职"]},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        job = self.create_job(graduation_year="2028")
        match = self.client.get(f"/api/jobs/{job['job_id']}/match").json()["match"]
        self.assertEqual(match["required_coverage"]["ratio"], 1.0)
        self.assertEqual(match["grade"], "NOT_RECOMMENDED")
        graduation = next(item for item in match["hard_conditions"] if item["name"] == "graduation_year")
        self.assertEqual(graduation["status"], "FAIL")

    def test_heuristic_is_configurable_and_explicitly_non_statistical(self) -> None:
        previous = {name: os.environ.get(name) for name in ("MATCH_HEURISTIC_VERSION", "MATCH_REQUIRED_COVERAGE", "MATCH_STRONG_REQUIRED_COVERAGE")}
        os.environ["MATCH_HEURISTIC_VERSION"] = "heuristic_test"
        os.environ["MATCH_REQUIRED_COVERAGE"] = "0.55"
        os.environ["MATCH_STRONG_REQUIRED_COVERAGE"] = "0.75"
        try:
            config = self.client.get("/api/matching/config").json()
            self.assertEqual(config["version"], "heuristic_test")
            self.assertEqual(config["match_required_coverage"], 0.55)
            self.assertEqual(config["strong_required_coverage"], 0.75)
            self.assertIn("非录用概率", config["disclaimer"])
            self.assertIn("categories never imply equality", config["skill_dictionary"]["matching_rule"])
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_llm_explanation_only_receives_deterministic_facts(self) -> None:
        preview = self.client.post("/api/parsing/resume/preview", json={"text": "Python FastAPI Vue 3"}).json()["preview"]
        self.confirm_candidate(preview)
        job = self.create_job()
        response = self.client.post(f"/api/jobs/{job['job_id']}/match/explanation")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["facts_unchanged"])
        self.assertEqual(body["result_fingerprint"], body["match"]["result_fingerprint"])
        self.assertEqual(self.llm.last_facts["grade"], body["match"]["grade"])
        self.assertNotIn("candidate", self.llm.last_facts)
        self.assertIn("启发式规则", body["explanation"])

    def test_missing_llm_keeps_manual_workflow_and_matching_available(self) -> None:
        other_temp = tempfile.TemporaryDirectory()
        try:
            app = create_app(
                db_path=str(Path(other_temp.name) / "no-llm.db"),
                session_secret="no-llm",
                llm_client=UnavailableLlmClient(),
            )
            with TestClient(app) as client:
                self.assertEqual(client.post("/api/auth/login", json={"username": "demo", "password": "demo"}).status_code, 200)
                capabilities = client.get("/api/parsing/capabilities").json()
                self.assertFalse(capabilities["llm_available"])
                self.assertEqual(client.post("/api/parsing/resume/preview", json={"text": "Python"}).status_code, 503)
                candidate = client.get("/api/candidate").json()["candidate"]
                updated = client.put("/api/candidate", json={**candidate, "version": candidate["version"], "skills": ["Python"]})
                self.assertEqual(updated.status_code, 200, updated.text)
                job = client.post("/api/jobs", json={"company_name": "Manual Co", "title": "Python", "required_skills": ["Python"], "preferred_skills": []})
                self.assertEqual(job.status_code, 201, job.text)
                job_id = job.json()["job"]["job_id"]
                self.assertEqual(client.get(f"/api/jobs/{job_id}/match").status_code, 200)
        finally:
            other_temp.cleanup()

    def test_matching_respects_authentication_and_candidate_isolation(self) -> None:
        job = self.create_job()
        anonymous = TestClient(self.app)
        self.assertEqual(anonymous.get(f"/api/jobs/{job['job_id']}/match").status_code, 401)
        admin = TestClient(self.app)
        self.assertEqual(admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}).status_code, 200)
        self.assertEqual(admin.post("/api/auth/users", json={"username": "alice", "password": "alice", "role": "user"}).status_code, 201)
        alice = TestClient(self.app)
        self.assertEqual(alice.post("/api/auth/login", json={"username": "alice", "password": "alice"}).status_code, 200)
        self.assertEqual(alice.get(f"/api/jobs/{job['job_id']}/match").status_code, 404)
        anonymous.close()
        admin.close()
        alice.close()

    def test_frontend_keeps_phase2_features_after_phase5_agentops_addition(self) -> None:
        src = Path(__file__).resolve().parents[1] / "frontend" / "src"
        sidebar = (src / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
        self.assertEqual(sidebar.count("{ id: '"), 7)
        self.assertTrue(any(path.name == "CareerAgentView.vue" for path in src.rglob("*.vue")))
        candidate = (src / "views" / "Candidate360View.vue").read_text(encoding="utf-8")
        for term in ("resume/extract", "resume/preview", "preview-flag", "async function save"):
            self.assertIn(term, candidate)
        jobs = (src / "views" / "JobCenterView.vue").read_text(encoding="utf-8")
        for term in ("jd/preview", "结果用于梳理事实", "hard_conditions", "required_coverage", "/match"):
            self.assertIn(term, jobs)


if __name__ == "__main__":
    unittest.main()
