from pathlib import Path
from typing import Protocol

from docx import Document as DocxDocument
from pptx import Presentation
from pypdf import PdfReader

from app.documents.models import DocumentSection, ParsedDocument


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt", ".md"}
NO_EXTRACTABLE_TEXT_MESSAGE = "No extractable text found. Scanned/image-only PDFs are not supported in Phase 4."


class UnsupportedDocumentTypeError(ValueError):
    pass


class NoExtractableTextError(ValueError):
    pass


class DocumentParser(Protocol):
    def supports(self, filename: str) -> bool:
        pass

    def parse(self, file_path: Path, original_filename: str) -> ParsedDocument:
        pass


def _extension(filename: str) -> str:
    return Path(filename).suffix.casefold()


def _clean_lines(value: str) -> str:
    return chr(10).join(line.strip() for line in value.splitlines() if line.strip())


def _document_title(original_filename: str) -> str:
    return Path(original_filename).stem.strip() or "Uploaded document"


class PdfParser:
    def supports(self, filename: str) -> bool:
        return _extension(filename) == ".pdf"

    def parse(self, file_path: Path, original_filename: str) -> ParsedDocument:
        reader = PdfReader(str(file_path))
        sections: list[DocumentSection] = []
        for index, page in enumerate(reader.pages, start=1):
            text = _clean_lines(page.extract_text() or "")
            if text:
                sections.append(DocumentSection(heading_path=[f"Page {index}"], content=text, locator=f"Page {index}"))
        if not sections:
            raise NoExtractableTextError(NO_EXTRACTABLE_TEXT_MESSAGE)
        return ParsedDocument(title=_document_title(original_filename), sections=sections)


class DocxParser:
    def supports(self, filename: str) -> bool:
        return _extension(filename) == ".docx"

    def parse(self, file_path: Path, original_filename: str) -> ParsedDocument:
        document = DocxDocument(str(file_path))
        sections: list[DocumentSection] = []
        heading_path: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            content = _clean_lines(chr(10).join(buffer))
            if content:
                sections.append(DocumentSection(heading_path=list(heading_path), content=content, locator=None))
            buffer.clear()

        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style is not None else ""
            if style_name.startswith("Heading"):
                flush()
                try:
                    level = int(style_name.replace("Heading", "").strip().split()[0])
                except (IndexError, ValueError):
                    level = 1
                level = max(1, min(level, 3))
                heading_path = heading_path[: level - 1] + [text]
            else:
                buffer.append(text)

        for table in document.tables:
            rows: list[str] = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                buffer.append(chr(10).join(rows))

        flush()
        if not sections:
            raise NoExtractableTextError("No extractable text found in the uploaded DOCX document.")
        return ParsedDocument(title=_document_title(original_filename), sections=sections)


class PptxParser:
    def supports(self, filename: str) -> bool:
        return _extension(filename) == ".pptx"

    def parse(self, file_path: Path, original_filename: str) -> ParsedDocument:
        presentation = Presentation(str(file_path))
        sections: list[DocumentSection] = []
        for index, slide in enumerate(presentation.slides, start=1):
            title = f"Slide {index}"
            parts: list[str] = []
            if slide.shapes.title is not None and getattr(slide.shapes.title, "text", "").strip():
                title = slide.shapes.title.text.strip()
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    text = _clean_lines(shape.text)
                    if text and text != title:
                        parts.append(text)
                if getattr(shape, "has_table", False):
                    rows: list[str] = []
                    for row in shape.table.rows:
                        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                        if cells:
                            rows.append(" | ".join(cells))
                    if rows:
                        parts.append(chr(10).join(rows))
            content = _clean_lines(chr(10).join(parts))
            if content:
                sections.append(DocumentSection(heading_path=[title], content=content, locator=f"Slide {index}"))
        if not sections:
            raise NoExtractableTextError("No extractable text found in the uploaded PPTX document.")
        return ParsedDocument(title=_document_title(original_filename), sections=sections)


class TextDocumentParser:
    def supports(self, filename: str) -> bool:
        return _extension(filename) in {".txt", ".md"}

    def parse(self, file_path: Path, original_filename: str) -> ParsedDocument:
        text = file_path.read_text(encoding="utf-8")
        if _extension(original_filename) == ".md":
            return self._parse_markdown(text, original_filename)
        paragraphs = [part.strip() for part in text.split(chr(10) + chr(10)) if part.strip()]
        if not paragraphs:
            raise NoExtractableTextError("No extractable text found in the uploaded text document.")
        return ParsedDocument(
            title=_document_title(original_filename),
            sections=[DocumentSection(heading_path=[], content=paragraph, locator=None) for paragraph in paragraphs],
        )

    def _parse_markdown(self, text: str, original_filename: str) -> ParsedDocument:
        sections: list[DocumentSection] = []
        heading_path: list[str] = []
        buffer: list[str] = []
        title = _document_title(original_filename)

        def flush() -> None:
            content = _clean_lines(chr(10).join(buffer))
            if content:
                sections.append(DocumentSection(heading_path=list(heading_path), content=content, locator=None))
            buffer.clear()

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                marker = stripped.split(" ", 1)[0]
                if marker and set(marker) == {"#"} and len(marker) <= 6 and len(stripped) > len(marker):
                    flush()
                    level = min(len(marker), 3)
                    heading = stripped[len(marker) :].strip()
                    heading_path = heading_path[: level - 1] + [heading]
                    if not sections and level == 1:
                        title = heading
                    continue
            buffer.append(line.rstrip())
        flush()
        if not sections:
            raise NoExtractableTextError("No extractable text found in the uploaded Markdown document.")
        return ParsedDocument(title=title, sections=sections)


PARSERS: tuple[DocumentParser, ...] = (PdfParser(), DocxParser(), PptxParser(), TextDocumentParser())


def get_parser(filename: str) -> DocumentParser:
    for parser in PARSERS:
        if parser.supports(filename):
            return parser
    raise UnsupportedDocumentTypeError("Unsupported file type. Supported types: .pdf, .docx, .pptx, .txt, .md")


def is_supported_filename(filename: str) -> bool:
    return _extension(filename) in SUPPORTED_EXTENSIONS
