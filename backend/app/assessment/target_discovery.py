from collections import defaultdict


CAPABILITY_PREDICATES = {
    "CALLS", "CONSUMES", "RECEIVES_FROM", "READS_FROM", "WRITES_TO",
    "PUBLISHES_TO", "PRODUCES", "EXPOSES", "DEPENDS_ON", "USES",
}


def rank_targets(source_id: str, rows: list[dict]) -> list[dict]:
    """Rank application peers by independently evidenced shared behavior."""
    by_entity: dict[str, dict] = defaultdict(lambda: {"features": set(), "claims": {}})
    for row in rows:
        if row["predicate"] not in CAPABILITY_PREDICATES:
            continue
        key = (row["predicate"], row["object_id"])
        profile = by_entity[row["entity_id"]]
        profile["name"] = row["entity_name"]
        profile["features"].add(key)
        profile["claims"].setdefault(key, row["claim_id"])
        profile.setdefault("objects", {})[key] = row["object_name"]
    source = by_entity.get(source_id)
    if not source or not source["features"]:
        return []
    suggestions = []
    for entity_id, profile in by_entity.items():
        if entity_id == source_id:
            continue
        shared = source["features"] & profile["features"]
        if not shared:
            continue
        suggestions.append({
            "entity_id": entity_id,
            "name": profile["name"],
            "matched_count": len(shared),
            "source_capability_count": len(source["features"]),
            "coverage": round(len(shared) / len(source["features"]), 3),
            "matched_capabilities": [f"{predicate.replace('_', ' ').lower()} {profile['objects'][predicate, object_id]}" for predicate, object_id in sorted(shared)],
            "claim_ids": sorted({profile["claims"][key] for key in shared}),
        })
    return sorted(suggestions, key=lambda item: (-item["matched_count"], -item["coverage"], item["name"]))[:5]


def select_supported_target(suggestions: list[dict]) -> dict | None:
    if not suggestions:
        return None
    best = suggestions[0]
    if best["matched_count"] < 2 or best["coverage"] < 0.5:
        return None
    if len(suggestions) > 1 and suggestions[1]["matched_count"] >= best["matched_count"]:
        return None
    return best
