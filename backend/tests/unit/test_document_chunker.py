import pytest

from app.documents.chunker import ChunkLimitExceededError, DocumentChunker
from app.documents.models import DocumentSection, ParsedDocument


def test_short_section_stays_one_chunk_with_metadata() -> None:
    document = ParsedDocument(
        title="Doc",
        sections=[DocumentSection(heading_path=["A", "B"], content="Short content.", locator="Page 1")],
    )

    chunks = DocumentChunker(max_chunk_chars=100, max_chunks_per_document=5).chunk(document)

    assert len(chunks) == 1
    assert chunks[0].sequence == 1
    assert chunks[0].heading_path == ["A", "B"]
    assert chunks[0].locator == "Page 1"
    assert chunks[0].content == "Short content."


def test_large_section_splits_on_paragraph_boundaries() -> None:
    document = ParsedDocument(
        title="Doc",
        sections=[
            DocumentSection(
                heading_path=["A"],
                content="""First paragraph.

Second paragraph.""",
                locator="Page 2",
            )
        ],
    )

    chunks = DocumentChunker(max_chunk_chars=20, max_chunks_per_document=5).chunk(document)

    assert [chunk.content for chunk in chunks] == ["First paragraph.", "Second paragraph."]
    assert all(len(chunk.content) <= 20 for chunk in chunks)
    assert [chunk.sequence for chunk in chunks] == [1, 2]
    assert all(chunk.heading_path == ["A"] for chunk in chunks)
    assert all(chunk.locator == "Page 2" for chunk in chunks)


def test_oversized_paragraph_splits_by_character_boundary() -> None:
    document = ParsedDocument(title="Doc", sections=[DocumentSection(content="abcdefghij")])

    chunks = DocumentChunker(max_chunk_chars=4, max_chunks_per_document=5).chunk(document)

    assert [chunk.content for chunk in chunks] == ["abcd", "efgh", "ij"]
    assert all(len(chunk.content) <= 4 for chunk in chunks)


def test_document_exceeding_chunk_limit_fails() -> None:
    document = ParsedDocument(title="Doc", sections=[DocumentSection(content="""one

two

three""")])

    with pytest.raises(ChunkLimitExceededError):
        DocumentChunker(max_chunk_chars=3, max_chunks_per_document=2).chunk(document)


def test_materialized_chunk_ids_are_deterministic() -> None:
    chunker = DocumentChunker(max_chunk_chars=100, max_chunks_per_document=5)
    drafts = chunker.chunk(ParsedDocument(title="Doc", sections=[DocumentSection(content="Stable")]))

    first = chunker.materialize("version-1", drafts)
    second = chunker.materialize("version-1", drafts)

    assert first == second
    assert first[0].version_id == "version-1"
