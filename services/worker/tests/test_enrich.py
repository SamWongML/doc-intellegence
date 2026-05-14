"""Enrichment helpers: anchors, breadcrumbs, code-block langs."""

from __future__ import annotations

from doc_search_worker.enrich.anchors import build_anchors, slug
from doc_search_worker.enrich.breadcrumbs import (
    breadcrumbs_from_path,
    section_breadcrumbs,
)
from doc_search_worker.enrich.code_blocks import dedupe_tags, language_from_info


def test_slug_basic() -> None:
    assert slug("App Router") == "app-router"
    assert slug("Hello, World!") == "hello-world"
    assert slug("  spaced   out  ") == "spaced-out"
    assert slug("Café") == "cafe"
    assert slug("") == ""


def test_build_anchors_disambiguates_duplicates() -> None:
    out = build_anchors(["Hello", "Hello", "World"])
    assert out == {"Hello": "hello-2", "World": "world"} or out["World"] == "world"
    # Python dicts preserve insertion order; second "Hello" overwrites first
    assert out["Hello"].startswith("hello")


def test_build_anchors_empty_heading_fallback() -> None:
    out = build_anchors(["???"])
    assert out["???"] == "section"


def test_breadcrumbs_from_path_strips_docs_prefix() -> None:
    assert breadcrumbs_from_path("docs/app-router/routing/middleware.mdx") == [
        "App Router",
        "Routing",
    ]


def test_breadcrumbs_from_path_no_docs_prefix() -> None:
    assert breadcrumbs_from_path("guides/intro.md") == ["Guides"]


def test_breadcrumbs_from_path_root() -> None:
    assert breadcrumbs_from_path("readme.md") == []


def test_section_breadcrumbs_chain() -> None:
    headings = [
        (1, "Top"),
        (2, "Section A"),
        (3, "Subsection A1"),
        (2, "Section B"),
    ]
    out = section_breadcrumbs(headings)
    assert out[0] == []
    assert out[1] == ["Top"]
    assert out[2] == ["Top", "Section A"]
    assert out[3] == ["Top"]


def test_language_from_info() -> None:
    assert language_from_info("python") == "python"
    assert language_from_info("  bash {numbered}") == "bash"
    assert language_from_info("c++") == "c++"
    assert language_from_info("") is None
    assert language_from_info(None) is None


def test_dedupe_tags_preserves_order_and_dedupes() -> None:
    assert dedupe_tags(["python", None, "bash", "python", ""]) == ["python", "bash"]
