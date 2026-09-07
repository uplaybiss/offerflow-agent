from __future__ import annotations


RESUME_TAILORING_CASES = (
    {"case_id": "python_fact_matches", "expected": "Python is matched when confirmed by candidate facts"},
    {"case_id": "docker_gap_not_added", "expected": "Docker remains a gap and is never added as a candidate skill"},
    {"case_id": "agent_tool_calling_emphasis", "expected": "Existing Agent Tool Calling evidence may be emphasized"},
    {"case_id": "kubernetes_years_not_fabricated", "expected": "Kubernetes and three years are rejected without evidence"},
    {"case_id": "jd_prompt_injection_ignored", "expected": "JD instructions cannot override the fact boundary"},
    {"case_id": "unsupported_metric_rejected", "expected": "A new 80 percent metric is marked unsupported"},
)
