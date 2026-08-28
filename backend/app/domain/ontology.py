from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ONTOLOGY_ROOT = REPOSITORY_ROOT / "ontology"


def _load_values(file_name: str, key: str) -> set[str]:
    ontology_file = ONTOLOGY_ROOT / file_name
    with ontology_file.open(encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    values = data.get(key, [])
    if not isinstance(values, list):
        raise ValueError(f"Ontology key {key} must contain a list")

    return {str(value) for value in values}


@lru_cache
def get_allowed_entity_types() -> set[str]:
    return _load_values("entity_types.yaml", "entity_types")


@lru_cache
def get_allowed_predicates() -> set[str]:
    return _load_values("predicates.yaml", "predicates")


def validate_entity_type(value: str) -> str:
    if value not in get_allowed_entity_types():
        raise ValueError(f"Unsupported entity_type: {value}")
    return value


def validate_predicate(value: str) -> str:
    if value not in get_allowed_predicates():
        raise ValueError(f"Unsupported predicate: {value}")
    return value
