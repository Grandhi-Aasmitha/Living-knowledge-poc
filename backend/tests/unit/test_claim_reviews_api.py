from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db.neo4j import get_neo4j_client
from app.main import create_app
from app.reviews.models import ClaimReviewRecord, PendingClaimReview


@pytest.fixture(autouse=True)
def clear_cached_settings_after_test():
    yield
    get_settings.cache_clear()


class FakeReviewRepository:
    def __init__(self) -> None:
        self.original = PendingClaimReview(
            claim_id="claim:file", subject_name="Billing Service", predicate="DEPENDS_ON",
            object_name="Orders Database", object_value=None, confidence=0.8,
            created_at=datetime.now(UTC), evidence_count=1,
        )
        self.pending = [self.original]
        self.history: list[ClaimReviewRecord] = []

    async def list_pending(self, namespace: str) -> list[PendingClaimReview]:
        return self.pending if namespace == "demo" else []

    async def list_history(self, namespace: str) -> list[ClaimReviewRecord]:
        return self.history if namespace == "demo" else []

    async def review(self, claim_id, request):
        if request.namespace != "demo":
            return None
        if request.decision == "REOPENED":
            if not any(item.claim_id == claim_id for item in self.history) or self.pending:
                return None
            self.pending = [self.original]
        else:
            if not any(claim.claim_id == claim_id for claim in self.pending):
                return None
            self.pending = [claim for claim in self.pending if claim.claim_id != claim_id]
        record = ClaimReviewRecord(
            id="review:1", claim_id=claim_id, namespace=request.namespace,
            subject_name="Billing Service", predicate="DEPENDS_ON", object_name="Orders Database",
            object_value=None, decision=request.decision, reviewer=request.reviewer,
            reason=request.reason, created_at=datetime.now(UTC),
        )
        self.history.append(record)
        return record


def make_client(monkeypatch, repository: FakeReviewRepository) -> TestClient:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_USERNAME", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("NEO4J_DATABASE", "neo4j")
    monkeypatch.setenv("FRONTEND_ORIGIN", "http://localhost:5173")
    monkeypatch.setenv("AI_PROVIDER", "local_rules")
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_neo4j_client] = lambda: SimpleNamespace()
    monkeypatch.setattr("app.api.claim_reviews.ClaimReviewRepository", lambda _client: repository)
    return TestClient(app)


def test_review_moves_uploaded_claim_from_pending_to_history(monkeypatch) -> None:
    client = make_client(monkeypatch, FakeReviewRepository())

    assert len(client.get("/api/claim-reviews?namespace=demo").json()) == 1
    response = client.post("/api/claim-reviews/claim:file", json={
        "namespace": "demo", "decision": "CONFIRMED", "reviewer": "Aasmitha", "reason": "Verified against the service inventory",
    })

    assert response.status_code == 200
    assert response.json()["decision"] == "CONFIRMED"
    assert client.get("/api/claim-reviews?namespace=demo").json() == []
    assert client.get("/api/claim-reviews/history?namespace=demo").json()[0]["reason"] == "Verified against the service inventory"
    assert client.post("/api/claim-reviews/claim:file", json={
        "namespace": "demo", "decision": "REJECTED", "reviewer": "Aasmitha", "reason": "Changed my mind",
    }).status_code == 409

    reopened = client.post("/api/claim-reviews/claim:file", json={
        "namespace": "demo", "decision": "REOPENED", "reviewer": "Aasmitha", "reason": "New source evidence needs review",
    })
    assert reopened.status_code == 200
    assert len(client.get("/api/claim-reviews?namespace=demo").json()) == 1
    assert len(client.get("/api/claim-reviews/history?namespace=demo").json()) == 2


def test_review_requires_reason_and_valid_decision(monkeypatch) -> None:
    client = make_client(monkeypatch, FakeReviewRepository())

    for decision, reason in [("CONFIRMED", "   "), ("PROPOSED", "Verified")]:
        response = client.post("/api/claim-reviews/claim:file", json={
            "namespace": "demo", "decision": decision, "reviewer": "Aasmitha", "reason": reason,
        })
        assert response.status_code == 422
    assert client.get("/api/claim-reviews?namespace=%20%20%20").status_code == 422
    assert client.post("/api/claim-reviews/claim:file", json={
        "namespace": "other", "decision": "CONFIRMED", "reviewer": "Aasmitha", "reason": "Verified",
    }).status_code == 409
