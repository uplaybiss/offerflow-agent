from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


DICTIONARY_VERSION = "skill_dictionary_v1"
LANGUAGE_DICTIONARY_VERSION = "language_dictionary_v1"


LANGUAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "english": ("english", "英语", "英文"),
    "chinese": ("chinese", "中文", "汉语", "普通话"),
    "japanese": ("japanese", "日语"),
    "korean": ("korean", "韩语"),
}


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


class LanguageDictionary:
    def __init__(self, aliases: dict[str, tuple[str, ...]] = LANGUAGE_ALIASES) -> None:
        self.aliases = aliases
        self._canonical_by_alias = {
            _key(alias): canonical
            for canonical, values in aliases.items()
            for alias in (*values, canonical)
        }

    def normalize(self, raw_language: str) -> dict[str, str]:
        original = str(raw_language or "").strip()
        key = _key(original)
        canonical = self._canonical_by_alias.get(key)
        if canonical:
            rule = "language_alias_v1"
        else:
            canonical = re.sub(r"[^0-9a-zA-Z]+", "_", original.casefold()).strip("_")
            if not canonical:
                canonical = key.replace(" ", "_")
            rule = "language_literal_v1"
        return {
            "raw_language": original,
            "canonical_language": canonical,
            "normalization_rule": rule,
        }

    def normalize_many(self, languages: Iterable[str]) -> list[dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for language in languages:
            item = self.normalize(str(language))
            canonical = item["canonical_language"]
            raw = item["raw_language"]
            if not raw or not canonical:
                continue
            current = grouped.setdefault(canonical, {
                "canonical_language": canonical,
                "variants": [],
                "normalization_rule": item["normalization_rule"],
            })
            variants = current["variants"]
            assert isinstance(variants, list)
            if raw not in variants:
                variants.append(raw)
        return list(grouped.values())

    def summary(self) -> dict[str, object]:
        return {
            "version": LANGUAGE_DICTIONARY_VERSION,
            "canonical_languages": sorted(self.aliases),
            "matching_rule": "explicit aliases only; proficiency is never inferred",
        }
