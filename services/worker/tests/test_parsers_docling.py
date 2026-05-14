"""Unit tests for the Docling parser using a fake DocumentConverter.

Real docling pulls 1-2 GB of model weights, so these tests inject a
``FakeConverter`` instead — that exercises every code path the integration
target (``DoclingDocument``) is expected to hit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from doc_search_worker.parsers import docling_parser

# --- Fakes that mimic the docling 2.x object surface we depend on. -----------


@dataclass
class _Label:
    name: str


@dataclass
class _Prov:
    page_no: int


@dataclass
class _Item:
    text: str = ""
    label: _Label | None = None
    prov: list[_Prov] = field(default_factory=list)


class _FakeDoclingDocument:
    def __init__(self, items: list[tuple[_Item, int]], markdown: str) -> None:
        self._items = items
        self._markdown = markdown

    def iterate_items(self) -> list[tuple[_Item, int]]:
        return list(self._items)

    def export_to_markdown(self) -> str:
        return self._markdown


@dataclass
class _FakeConversionResult:
    document: _FakeDoclingDocument


class _FakeConverter:
    def __init__(self, document: _FakeDoclingDocument) -> None:
        self._document = document
        self.calls: list[str] = []

    def convert(self, source: str) -> _FakeConversionResult:
        self.calls.append(source)
        return _FakeConversionResult(document=self._document)


# --- Tests --------------------------------------------------------------------


def test_is_pdf_or_office_recognises_common_mime_types() -> None:
    assert docling_parser.is_pdf_or_office("application/pdf")
    assert docling_parser.is_pdf_or_office("application/pdf; charset=utf-8")
    assert docling_parser.is_pdf_or_office(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert not docling_parser.is_pdf_or_office("text/html")
    assert not docling_parser.is_pdf_or_office("")


def test_ext_for_content_type_maps_common_formats() -> None:
    assert docling_parser.ext_for_content_type("application/pdf") == ".pdf"
    assert (
        docling_parser.ext_for_content_type(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        == ".pptx"
    )
    assert docling_parser.ext_for_content_type("application/octet-stream") == ".bin"


def test_parse_returns_markdown_and_page_anchors() -> None:
    items = [
        (
            _Item(text="Introduction", label=_Label("SECTION_HEADER"), prov=[_Prov(page_no=1)]),
            0,
        ),
        (_Item(text="Body text", label=_Label("PARAGRAPH"), prov=[_Prov(page_no=1)]), 0),
        (
            _Item(text="Specifications", label=_Label("SECTION_HEADER"), prov=[_Prov(page_no=12)]),
            0,
        ),
        (
            _Item(text="Specifications", label=_Label("SECTION_HEADER"), prov=[_Prov(page_no=14)]),
            0,
        ),
    ]
    document = _FakeDoclingDocument(
        items=items,
        markdown="# Introduction\n\nBody text\n\n## Specifications\n\n| col |\n|-----|\n| val |\n",
    )
    converter = _FakeConverter(document)

    result = docling_parser.parse("/tmp/sample.pdf", converter=converter)

    assert converter.calls == ["/tmp/sample.pdf"]
    assert result.title == "Introduction"
    # Distinct pages observed across all items: 1, 12, 14.
    assert result.page_count == 3
    # Each section header maps to ``page-N``; duplicate text keys collapse so
    # the final mapping reflects the *last* occurrence (page 14 here), matching
    # the existing ``build_anchors`` semantics for the markdown parser.
    assert result.anchors == {
        "Introduction": "page-1",
        "Specifications": "page-14",
    }
    assert "| col |" in result.markdown  # tables preserved


def test_parse_falls_back_to_slug_when_page_missing() -> None:
    items = [
        (_Item(text="Overview", label=_Label("SECTION_HEADER"), prov=[]), 0),
        (_Item(text="Overview", label=_Label("SECTION_HEADER"), prov=[]), 0),
    ]
    document = _FakeDoclingDocument(items=items, markdown="# Overview\n")
    result = docling_parser.parse("/tmp/x.pdf", converter=_FakeConverter(document))

    assert result.title == "Overview"
    # Duplicate header → second entry gets -2 suffix. Both share the text key
    # so only the latest is retained — that latest must be the -2 variant.
    assert result.anchors == {"Overview": "overview-2"}
    assert result.page_count == 0


def test_parse_bytes_uses_extension_from_content_type() -> None:
    captured: list[str] = []

    document = _FakeDoclingDocument(items=[], markdown="hello\n")

    class _Recorder:
        def convert(self, source: str) -> _FakeConversionResult:
            captured.append(source)
            return _FakeConversionResult(document=document)

    result = docling_parser.parse_bytes(
        b"%PDF-1.4 fake bytes",
        content_type="application/pdf",
        converter=_Recorder(),
    )
    assert result.markdown == "hello\n"
    assert captured and captured[0].endswith(".pdf")


def test_parse_handles_doc_without_iterate_items() -> None:
    class _Minimal:
        def export_to_markdown(self) -> str:
            return "just a body\n"

    class _MinimalConverter:
        def convert(self, source: str) -> _FakeConversionResult:
            return _FakeConversionResult(document=_Minimal())  # type: ignore[arg-type]

    result = docling_parser.parse("/tmp/x.pdf", converter=_MinimalConverter())
    assert result.title == "Untitled"
    assert result.anchors == {}
    assert result.markdown == "just a body\n"
