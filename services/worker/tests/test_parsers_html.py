"""HTML parsing: Trafilatura + selectolax anchor extraction + chrome strip."""

from __future__ import annotations

from doc_search_worker.enrich.html_anchors import extract_html_anchors, extract_title
from doc_search_worker.enrich.html_cleanup import strip_chrome
from doc_search_worker.parsers import html_trafilatura


def test_trafilatura_extracts_next_js_docs(nextjs_html: str) -> None:
    result = html_trafilatura.extract(nextjs_html)
    assert result is not None
    md = result.markdown.lower()
    assert "middleware" in md
    assert "using jwt" in md
    # Chrome / nav stripped.
    assert "edit this page" not in md
    assert "was this helpful" not in md


def test_trafilatura_returns_none_for_spa(spa_html: str) -> None:
    assert html_trafilatura.extract(spa_html) is None


def test_html_anchors_pulls_real_ids(nextjs_html: str) -> None:
    anchors = extract_html_anchors(nextjs_html)
    assert anchors["Using JWT"] == "using-jwt"
    assert anchors["Convention"] == "convention"
    assert anchors["Middleware"] == "middleware"


def test_html_anchors_fallback_when_no_ids() -> None:
    html = "<html><body><h2>Top</h2><h3>Detail</h3></body></html>"
    anchors = extract_html_anchors(html)
    assert anchors["Top"] == "top"
    assert anchors["Detail"] == "detail"


def test_extract_title_prefers_h1(nextjs_html: str) -> None:
    assert extract_title(nextjs_html) == "Middleware"


def test_extract_title_falls_back_to_title_tag() -> None:
    html = "<html><head><title>Hello</title></head><body><p>No h1</p></body></html>"
    assert extract_title(html) == "Hello"


def test_strip_chrome_removes_blocklisted_lines() -> None:
    md = (
        "# Doc title\n\n"
        "Content.\n\n"
        "Edit this page on GitHub\n"
        "\n"
        "Was this helpful?\n"
        "\n"
        "Previous\n"
        "Next\n"
        "\n"
        "More content.\n"
    )
    cleaned = strip_chrome(md)
    lowered = cleaned.lower()
    assert "edit this page" not in lowered
    assert "was this helpful" not in lowered
    assert "previous" not in lowered
    assert "More content." in cleaned
    # Blank-line runs collapsed.
    assert "\n\n\n" not in cleaned


def test_strip_chrome_removes_leading_nav_list() -> None:
    md = "- Home\n- Docs\n- About\n\n# Real title\n\nBody.\n"
    cleaned = strip_chrome(md)
    assert cleaned.startswith("# Real title")
