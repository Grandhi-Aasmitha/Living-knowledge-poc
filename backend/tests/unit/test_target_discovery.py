from app.assessment.target_discovery import rank_targets, select_supported_target


def row(entity_id, entity_name, predicate, object_id, object_name):
    return {"entity_id": entity_id, "entity_name": entity_name,
            "claim_id": f"{entity_id}:{predicate}:{object_id}", "predicate": predicate,
            "object_id": object_id, "object_name": object_name}


def test_ranks_capability_peer_over_portal_and_archive():
    rows = [
        row("legacy", "Legacy Claims", "CALLS", "fraud", "Fraud API"),
        row("legacy", "Legacy Claims", "WRITES_TO", "ledger", "Claims Ledger"),
        row("legacy", "Legacy Claims", "PUBLISHES_TO", "topic", "Decision Topic"),
        row("digital", "Digital Claims", "CALLS", "fraud", "Fraud API"),
        row("digital", "Digital Claims", "WRITES_TO", "ledger", "Claims Ledger"),
        row("digital", "Digital Claims", "PUBLISHES_TO", "topic", "Decision Topic"),
        row("portal", "Claims Portal", "READS_FROM", "ledger", "Claims Ledger"),
        row("archive", "Claims Archive", "READS_FROM", "ledger", "Claims Ledger"),
    ]
    suggestions = rank_targets("legacy", rows)
    assert [item["name"] for item in suggestions] == ["Digital Claims"]
    assert select_supported_target(suggestions)["name"] == "Digital Claims"


def test_does_not_select_weak_or_tied_candidates():
    rows = [row("source", "Source", "CALLS", "a", "API A"),
            row("source", "Source", "WRITES_TO", "b", "Database B"),
            row("candidate", "Candidate", "CALLS", "a", "API A")]
    assert select_supported_target(rank_targets("source", rows)) is None
    rows.extend([row("candidate", "Candidate", "WRITES_TO", "b", "Database B"),
                 row("peer", "Peer", "CALLS", "a", "API A"),
                 row("peer", "Peer", "WRITES_TO", "b", "Database B")])
    assert select_supported_target(rank_targets("source", rows)) is None
