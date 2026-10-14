import asyncio
import logging
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from app.ai.client import AIProviderError
from app.services.file_ingestion_service import FileIngestionService

T = TypeVar("T", bound=BaseModel)


def run(coro):
    return asyncio.run(coro)


class FailingStructuredAIClient:
    async def generate_structured(self, prompt: str, response_model: type[T]) -> T:
        raise AIProviderError("Tabnine CLI provider returned schema-invalid JSON")


class FakeDocumentRepository:
    async def get_document_by_external_id(self, source_id: str, external_id: str, namespace: str):
        return None


class UnusedRepository:
    pass


def test_file_ingestion_logs_safe_ai_failure_context(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        service = FileIngestionService(
            ai_client=FailingStructuredAIClient(),
            source_repository=UnusedRepository(),
            document_repository=FakeDocumentRepository(),
            entity_repository=UnusedRepository(),
            claim_repository=UnusedRepository(),
            upload_directory=str(tmp_path / "uploads"),
            max_upload_size_mb=10,
            max_chunk_chars=6000,
            max_chunks_per_document=20,
        )
        content = b"# Safe Synthetic\n\nThe Demo Service consumes the Demo Topic."

        with caplog.at_level(logging.INFO, logger="app.services.file_ingestion_service"):
            with pytest.raises(AIProviderError):
                await service.ingest(content, "safe-demo.md", namespace="test")

        messages = "\n".join(record.getMessage() for record in caplog.records)
        assert "Starting file ingestion" in messages
        assert "File ingestion parsed" in messages
        assert "File ingestion AI extraction failed" in messages
        assert "provider_error=Tabnine CLI provider returned schema-invalid JSON" in messages
        assert "extension=.md" in messages
        assert "namespace=test" in messages
        assert "The Demo Service consumes the Demo Topic" not in messages
        assert "safe-demo.md" not in messages

    run(scenario())
