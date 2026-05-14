"""Markdown parser: title, headings, code langs, canonical body."""

from __future__ import annotations

from pathlib import Path

from doc_search_worker.parsers.markdown import parse_markdown


def test_parse_with_frontmatter_and_code(sample_repo_dir: Path) -> None:
    content = (sample_repo_dir / "docs/app-router/routing/middleware.mdx").read_text("utf-8")
    parsed = parse_markdown(content)
    assert parsed.title == "Middleware"  # from frontmatter
    assert parsed.metadata["description"] == "Runs before requests are completed."
    levels = {level for level, _ in parsed.headings}
    texts = [text for _, text in parsed.headings]
    assert levels == {1, 2, 3}
    assert "Welcome" in texts
    assert "Installation" in texts
    assert "Verify" in texts
    assert "bash" in parsed.code_languages
    assert "python" in parsed.code_languages


def test_canonical_normalizes_bullets() -> None:
    raw = "# t\n\n* a\n+ b\n- c\n"
    parsed = parse_markdown(raw)
    assert "* a" not in parsed.canonical
    assert "+ b" not in parsed.canonical
    assert parsed.canonical.count("- ") >= 3


def test_canonical_collapses_blank_lines() -> None:
    raw = "# t\n\n\n\nhello\n"
    parsed = parse_markdown(raw)
    assert "\n\n\n" not in parsed.canonical


def test_canonical_keeps_bullets_inside_code_block() -> None:
    raw = "# t\n\n```\n* not a bullet\n```\n"
    parsed = parse_markdown(raw)
    assert "* not a bullet" in parsed.canonical


def test_title_falls_back_to_first_h1() -> None:
    parsed = parse_markdown("# The Title\n\nbody\n")
    assert parsed.title == "The Title"


def test_title_default_when_no_headings() -> None:
    parsed = parse_markdown("body without headings\n", default_title="X")
    assert parsed.title == "X"
