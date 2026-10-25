from pathlib import Path

import pytest
from docx import Document as DocxDocument
from pptx import Presentation
from pypdf import PdfWriter
from PIL import Image, ImageDraw

from app.documents.parsers import (
    DOCUMENT_PARSE_ERROR_MESSAGE,
    NO_EXTRACTABLE_TEXT_MESSAGE,
    DocxParser,
    DocumentParseError,
    NoExtractableTextError,
    PdfParser,
    PptxParser,
    TextDocumentParser,
    UnsupportedDocumentTypeError,
    get_parser,
)


def test_txt_parser_splits_paragraph_groups(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("""First paragraph.

Second paragraph.""", encoding="utf-8")

    parsed = TextDocumentParser().parse(path, "notes.txt")

    assert parsed.title == "notes"
    assert [section.content for section in parsed.sections] == ["First paragraph.", "Second paragraph."]


def test_markdown_parser_preserves_heading_hierarchy(tmp_path: Path) -> None:
    path = tmp_path / "demo.md"
    path.write_text(
        """# Price Event Flow

Intro.

## Publishing

The Ingestion Service publishes.""",
        encoding="utf-8",
    )

    parsed = TextDocumentParser().parse(path, "demo.md")

    assert parsed.title == "Price Event Flow"
    assert parsed.sections[0].heading_path == ["Price Event Flow"]
    assert parsed.sections[1].heading_path == ["Price Event Flow", "Publishing"]


def test_docx_parser_preserves_headings_paragraphs_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "demo.docx"
    document = DocxDocument()
    document.add_heading("System Flow", level=1)
    document.add_paragraph("The Aggregator Service consumes the Transformed Price Topic.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Service"
    table.rows[0].cells[1].text = "Aggregator Service"
    document.save(path)

    parsed = DocxParser().parse(path, "demo.docx")

    assert parsed.sections[0].heading_path == ["System Flow"]
    combined = chr(10).join(section.content for section in parsed.sections)
    assert "Aggregator Service consumes" in combined
    assert "Service | Aggregator Service" in combined


def test_pptx_parser_extracts_slide_text_and_table(tmp_path: Path) -> None:
    path = tmp_path / "demo.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "Price Event Flow"
    textbox = slide.shapes.add_textbox(914400, 914400, 5000000, 500000)
    textbox.text = "The Ingestion Service publishes to the Transformed Price Topic."
    table_shape = slide.shapes.add_table(1, 2, 914400, 1828800, 5000000, 500000)
    table_shape.table.cell(0, 0).text = "Topic"
    table_shape.table.cell(0, 1).text = "Transformed Price Topic"
    presentation.save(path)

    parsed = PptxParser().parse(path, "demo.pptx")

    assert parsed.sections[0].heading_path == ["Price Event Flow"]
    assert parsed.sections[0].locator == "Slide 1"
    assert "Ingestion Service publishes" in parsed.sections[0].content
    assert "Topic | Transformed Price Topic" in parsed.sections[0].content


def test_blank_pdf_raises_no_extractable_text(tmp_path: Path) -> None:
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as file:
        writer.write(file)

    with pytest.raises(NoExtractableTextError, match=NO_EXTRACTABLE_TEXT_MESSAGE):
        get_parser("blank.pdf").parse(path, "blank.pdf")


def test_image_only_pdf_uses_ocr_and_preserves_page_locator(tmp_path: Path) -> None:
    import asyncio

    image = Image.new("RGB", (800, 220), "white")
    ImageDraw.Draw(image).text((30, 30), "Ops Team owns Routing Service", fill="black")
    path = tmp_path / "scan.pdf"
    image.save(path, "PDF")

    class FakeOcr:
        async def read_image_text(self, image_png: bytes) -> str:
            assert image_png.startswith(b"\x89PNG")
            return "Ops Team owns Routing Service."

    parsed = asyncio.run(PdfParser().parse_with_ocr(path, "scan.pdf", FakeOcr()))

    assert parsed.sections[0].content == "Ops Team owns Routing Service."
    assert parsed.sections[0].locator == "Page 1"


def test_corrupt_pdf_raises_safe_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"this is not a pdf")

    with pytest.raises(DocumentParseError, match=DOCUMENT_PARSE_ERROR_MESSAGE):
        get_parser("corrupt.pdf").parse(path, "corrupt.pdf")


def test_invalid_utf8_text_raises_safe_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(DocumentParseError, match=DOCUMENT_PARSE_ERROR_MESSAGE):
        TextDocumentParser().parse(path, "invalid.txt")


def test_unsupported_extension_rejected() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        get_parser("demo.exe")
