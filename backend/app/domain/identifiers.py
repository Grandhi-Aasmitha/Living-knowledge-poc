import hashlib
import re


def stable_entity_id(namespace: str, entity_type: str, canonical_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", canonical_name.casefold()).strip("-")
    return f"{namespace.casefold()}:{entity_type.casefold()}:{slug}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_automatic_gap_id(rule_id: str, entity_id: str) -> str:
    digest = sha256_text(f"{rule_id}|{entity_id}")[:24]
    return f"auto:gap:{rule_id}:{digest}"


def normalize_filename(filename: str) -> str:
    return re.sub(r"\s+", " ", filename.strip()).casefold()


def stable_source_document_id(filename: str) -> str:
    return f"file:document:{sha256_text(normalize_filename(filename))[:24]}"


def stable_source_version_id(document_id: str, content_hash: str) -> str:
    return f"file:version:{sha256_text(f'{document_id}:{content_hash}')[:24]}"


def stable_source_chunk_id(version_id: str, sequence: int, content_hash: str) -> str:
    return f"file:chunk:{sha256_text(f'{version_id}:{sequence}:{content_hash}')[:24]}"


def stable_claim_id(
    subject_entity_id: str,
    predicate: str,
    object_entity_id: str | None,
    object_value: str | None,
    scope_entity_id: str | None,
) -> str:
    object_part = object_entity_id if object_entity_id is not None else f"value:{object_value}"
    scope_part = scope_entity_id or ""
    return f"file:claim:{sha256_text(f'{subject_entity_id}|{predicate}|{object_part}|{scope_part}')[:24]}"


def stable_evidence_id(claim_id: str, source_chunk_id: str, evidence_excerpt: str) -> str:
    return f"file:evidence:{sha256_text(f'{claim_id}|{source_chunk_id}|{evidence_excerpt}')[:24]}"
