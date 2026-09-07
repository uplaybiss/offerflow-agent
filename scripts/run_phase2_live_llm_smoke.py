from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from core.errors import ExternalServiceError
from parsing.llm import DashScopeLlmClient
from parsing.service import ParsingService


def run() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    client = DashScopeLlmClient()
    if not client.available:
        print("PHASE 2 LIVE LLM SMOKE: SKIP - DASHSCOPE_API_KEY is not configured")
        return

    service = ParsingService(client)
    try:
        resume = service.resume_preview(
            "合成测试简历：李同学，2027 年毕业，计算机硕士，目标岗位 AI 应用工程师，"
            "接受上海，技能 Python、FastAPI、Vue 3、LangChain。"
        )["preview"]
        jd = service.jd_preview(
            "合成测试 JD：示例科技招聘 AI 应用工程师，上海全职，面向 2027 届硕士。"
            "必须掌握 Python 和 FastAPI，熟悉 Vue 3 优先，截止日期 2030-12-31。"
        )["preview"]
    except ExternalServiceError as exc:
        print(f"PHASE 2 LIVE LLM SMOKE: FAIL - {exc}")
        raise SystemExit(1) from None
    if "FastAPI" not in resume["skills"] or "FastAPI" not in jd["required_skills"]:
        raise RuntimeError("真实模型未保留输入中的具体技能 FastAPI")
    if resume["current_resume_parsed"]["parser"]["model"] != client.model:
        raise RuntimeError("简历解析结果缺少模型指纹")
    if jd["parser"]["model"] != client.model:
        raise RuntimeError("JD 解析结果缺少模型指纹")
    print("PHASE 2 LIVE LLM SMOKE: PASS")
    print(f"  provider={client.provider}, model={client.model}")
    print(f"  resume_skills={resume['skills']}")
    print(f"  jd_required_skills={jd['required_skills']}, jd_preferred_skills={jd['preferred_skills']}")


if __name__ == "__main__":
    run()
