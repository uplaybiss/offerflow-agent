from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


DICTIONARY_VERSION = "skill_dictionary_v1"


@dataclass(frozen=True)
class SkillDefinition:
    canonical_skill: str
    skill_category: str
    aliases: tuple[str, ...]


DEFINITIONS = (
    SkillDefinition("python", "programming_language", ("python", "python3", "py")),
    SkillDefinition("java", "programming_language", ("java",)),
    SkillDefinition("javascript", "programming_language", ("javascript", "js", "ecmascript")),
    SkillDefinition("typescript", "programming_language", ("typescript", "ts")),
    SkillDefinition("c++", "programming_language", ("c++", "cpp")),
    SkillDefinition("fastapi", "backend_framework", ("fastapi", "fast api", "fast-api")),
    SkillDefinition("django", "backend_framework", ("django",)),
    SkillDefinition("flask", "backend_framework", ("flask",)),
    SkillDefinition("spring_boot", "backend_framework", ("spring boot", "springboot", "spring-boot")),
    SkillDefinition("vue", "frontend_framework", ("vue", "vue.js", "vuejs", "vue 2", "vue 3", "vue2", "vue3")),
    SkillDefinition("react", "frontend_framework", ("react", "react.js", "reactjs")),
    SkillDefinition("langchain", "llm_framework", ("langchain", "lang chain")),
    SkillDefinition("llamaindex", "llm_framework", ("llamaindex", "llama index")),
    SkillDefinition("rag", "ai_application", ("rag", "retrieval augmented generation", "检索增强生成")),
    SkillDefinition("agent", "ai_application", ("agent", "ai agent", "智能体")),
    SkillDefinition("llm", "ai_application", ("llm", "large language model", "大语言模型", "大模型")),
    SkillDefinition("qwen", "model_family", ("qwen", "通义千问", "千问")),
    SkillDefinition("chromadb", "vector_database", ("chromadb", "chroma db", "chroma")),
    SkillDefinition("milvus", "vector_database", ("milvus",)),
    SkillDefinition("mysql", "database", ("mysql",)),
    SkillDefinition("postgresql", "database", ("postgresql", "postgres", "pgsql")),
    SkillDefinition("sqlite", "database", ("sqlite", "sqlite3")),
    SkillDefinition("redis", "database", ("redis",)),
    SkillDefinition("sql", "query_language", ("sql",)),
    SkillDefinition("rest_api", "api_style", ("rest api", "restful api", "restful", "rest")),
    SkillDefinition("pytest", "test_framework", ("pytest",)),
    SkillDefinition("junit", "test_framework", ("junit",)),
    SkillDefinition("selenium", "test_tool", ("selenium",)),
    SkillDefinition("playwright", "test_tool", ("playwright",)),
    SkillDefinition("postman", "test_tool", ("postman",)),
    SkillDefinition("jmeter", "performance_test_tool", ("jmeter", "apache jmeter")),
    SkillDefinition("git", "developer_tool", ("git",)),
    SkillDefinition("linux", "operating_system", ("linux",)),
    SkillDefinition("docker", "container", ("docker",)),
    SkillDefinition("kubernetes", "orchestration", ("kubernetes", "k8s")),
    SkillDefinition("fastapi_testclient", "test_tool", ("fastapi testclient",)),
)


def _key(value: str) -> str:
    return re.sub(r"[\s._-]+", " ", str(value or "").strip().casefold()).strip()


class SkillDictionary:
    def __init__(self, definitions: Iterable[SkillDefinition] = DEFINITIONS) -> None:
        self.definitions = tuple(definitions)
        self._aliases: dict[str, SkillDefinition] = {}
        for definition in self.definitions:
            for alias in (*definition.aliases, definition.canonical_skill):
                self._aliases[_key(alias)] = definition

    def normalize(self, raw_skill: str) -> dict[str, str]:
        original = str(raw_skill or "").strip()
        definition = self._aliases.get(_key(original))
        if definition:
            return {
                "raw_skill": original,
                "canonical_skill": definition.canonical_skill,
                "skill_category": definition.skill_category,
                "normalization_rule": "dictionary_alias_v1",
            }
        canonical = re.sub(r"[^0-9a-zA-Z+#.]+", "_", original.casefold()).strip("_") or _key(original).replace(" ", "_")
        return {
            "raw_skill": original,
            "canonical_skill": canonical,
            "skill_category": "other",
            "normalization_rule": "literal_fallback_v1",
        }

    def normalize_many(self, skills: Iterable[str]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for skill in skills:
            item = self.normalize(str(skill))
            if item["raw_skill"] and item["canonical_skill"] not in seen:
                result.append(item)
                seen.add(item["canonical_skill"])
        return result

    def summary(self) -> dict[str, object]:
        return {
            "version": DICTIONARY_VERSION,
            "canonical_skill_count": len(self.definitions),
            "categories": sorted({item.skill_category for item in self.definitions}),
            "matching_rule": "canonical skills match; categories never imply equality",
        }
