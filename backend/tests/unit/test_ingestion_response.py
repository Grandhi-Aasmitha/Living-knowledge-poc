import asyncio
from io import BytesIO
from types import SimpleNamespace

from starlette.datastructures import UploadFile

from app.api.sources import upload_file
from app.services.file_ingestion_service import EntityResolutionSummary, IngestionResult


def test_upload_serializes_nested_entity_decisions_and_learned_aliases() -> None:
    class FakeIngestionService:
        async def ingest(self, content: bytes, original_filename: str, namespace: str, force: bool = False) -> IngestionResult:
            assert content == b"TSTVS publishes events."
            assert original_filename == "team.md"
            assert namespace == "team"
            return IngestionResult(
                document_id="document", version_id="version", status="INGESTED",
                chunks_processed=1, entities_created=0, entities_reused=1,
                claims_created=0, claims_reused=0, evidence_created=0, claims_rejected=1,
                unresolved_terms=["Dispatch (entity identity needs review)"],
                entity_resolutions=[
                    EntityResolutionSummary(
                        observed_name="TSTVS", observed_type="SYSTEM", action="MATCH",
                        canonical_entity_id="system", canonical_name="TSTVS System",
                        alias_learned=True,
                    ),
                    EntityResolutionSummary(
                        observed_name="Dispatch", observed_type="TOPIC", action="NEEDS_REVIEW",
                        reason="Two possible topics.",
                    ),
                ],
            )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(file_ingestion_service=FakeIngestionService())))
    file = UploadFile(filename="team.md", file=BytesIO(b"TSTVS publishes events."))
    response = asyncio.run(upload_file(request, file, namespace="team", force=False))

    payload = response.model_dump(mode="json")
    assert payload["entity_resolutions"][0]["canonical_name"] == "TSTVS System"
    assert payload["entity_resolutions"][0]["alias_learned"] is True
    assert payload["entity_resolutions"][1]["action"] == "NEEDS_REVIEW"
    assert payload["entity_resolutions"][1]["canonical_entity_id"] is None


def test_unchanged_upload_returns_empty_learning_report() -> None:
    class FakeIngestionService:
        async def ingest(self, **kwargs) -> IngestionResult:
            return IngestionResult(
                document_id="document", version_id="version", status="UNCHANGED",
                chunks_processed=0, entities_created=0, entities_reused=0,
                claims_created=0, claims_reused=0, evidence_created=0, claims_rejected=0,
            )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(file_ingestion_service=FakeIngestionService())))
    file = UploadFile(filename="team.md", file=BytesIO(b"unchanged"))
    response = asyncio.run(upload_file(request, file, namespace="team", force=False))
    assert response.entity_resolutions == []
    assert response.status == "UNCHANGED"


def test_force_reprocessing_form_flag_is_forwarded_as_boolean() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.sources import router

    class FakeIngestionService:
        async def ingest(self, content, original_filename, namespace, force):
            assert force is True
            assert namespace == "team"
            return IngestionResult(document_id="document", version_id="revision-2", status="INGESTED", chunks_processed=1, entities_created=0, entities_reused=0, claims_created=0, claims_reused=0, evidence_created=0, claims_rejected=0)

    app = FastAPI()
    app.state.file_ingestion_service = FakeIngestionService()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/sources/files", files={"file": ("team.md", b"Known document", "text/markdown")}, data={"namespace": "team", "force": "true"})
    assert response.status_code == 200
    assert response.json()["version_id"] == "revision-2"
