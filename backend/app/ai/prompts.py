from functools import lru_cache
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_ROOT = REPOSITORY_ROOT / "prompts"


def _read_prompt(relative_path: str) -> str:
    return (PROMPTS_ROOT / relative_path).read_text(encoding="utf-8")


@lru_cache
def get_question_generation_prompt() -> str:
    return _read_prompt("curation/question_generation/v2.md")


@lru_cache
def get_answer_interpretation_prompt() -> str:
    return _read_prompt("curation/answer_interpretation/v2.md")


@lru_cache
def get_extraction_prompt() -> str:
    return _read_prompt("extraction/v1.md")


@lru_cache
def get_entity_resolution_prompt() -> str:
    return _read_prompt("entity_resolution/v1.md")


@lru_cache
def get_assistant_query_planning_prompt() -> str:
    return _read_prompt("assistant/query_planning/v1.md")


@lru_cache
def get_assistant_answer_generation_prompt() -> str:
    return _read_prompt("assistant/answer_generation/v1.md")
