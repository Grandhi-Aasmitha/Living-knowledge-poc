from dataclasses import dataclass

from app.documents.models import DocumentSection, ParsedDocument, SourceChunk
from app.domain.identifiers import sha256_text, stable_source_chunk_id


class ChunkLimitExceededError(ValueError):
    pass


@dataclass(frozen=True)
class DraftChunk:
    sequence: int
    heading_path: list[str]
    content: str
    locator: str | None
    content_hash: str


class DocumentChunker:
    def __init__(self, max_chunk_chars: int = 6000, max_chunks_per_document: int = 20) -> None:
        if max_chunk_chars <= 0:
            raise ValueError("max_chunk_chars must be positive")
        if max_chunks_per_document <= 0:
            raise ValueError("max_chunks_per_document must be positive")
        self._max_chunk_chars = max_chunk_chars
        self._max_chunks_per_document = max_chunks_per_document

    def chunk(self, document: ParsedDocument) -> list[DraftChunk]:
        chunks: list[DraftChunk] = []
        for section in document.sections:
            for content in self._split_section(section):
                sequence = len(chunks) + 1
                chunks.append(
                    DraftChunk(
                        sequence=sequence,
                        heading_path=list(section.heading_path),
                        content=content,
                        locator=section.locator,
                        content_hash=sha256_text(content),
                    )
                )
                if len(chunks) > self._max_chunks_per_document:
                    raise ChunkLimitExceededError(
                        f"Document exceeds the configured limit of {self._max_chunks_per_document} chunks."
                    )
        return chunks

    def materialize(self, version_id: str, chunks: list[DraftChunk]) -> list[SourceChunk]:
        return [
            SourceChunk(
                id=stable_source_chunk_id(version_id, chunk.sequence, chunk.content_hash),
                version_id=version_id,
                sequence=chunk.sequence,
                heading_path=chunk.heading_path,
                content=chunk.content,
                locator=chunk.locator,
                content_hash=chunk.content_hash,
            )
            for chunk in chunks
        ]

    def _split_section(self, section: DocumentSection) -> list[str]:
        content = section.content.strip()
        if not content:
            return []
        separator = chr(10) + chr(10)
        paragraphs = [paragraph.strip() for paragraph in content.split(separator) if paragraph.strip()]
        if not paragraphs:
            paragraphs = [content]

        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(paragraph) > self._max_chunk_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_oversized_paragraph(paragraph))
                continue
            candidate = paragraph if not current else separator.join([current, paragraph])
            if len(candidate) <= self._max_chunk_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = paragraph
        if current:
            chunks.append(current)
        return chunks

    def _split_oversized_paragraph(self, paragraph: str) -> list[str]:
        return [paragraph[index : index + self._max_chunk_chars] for index in range(0, len(paragraph), self._max_chunk_chars)]
