"""Hashing helpers."""

from __future__ import annotations

from doc_search_worker.hashing import content_hash, document_id, normalize_whitespace


def test_normalize_collapses_blank_lines() -> None:
    text = "a\n\n\n\nb\n"
    assert normalize_whitespace(text) == "a\n\nb\n"


def test_normalize_strips_trailing_ws() -> None:
    text = "line one   \nline two\t\n"
    assert normalize_whitespace(text) == "line one\nline two\n"


def test_normalize_idempotent() -> None:
    raw = "x\r\n  \r\n\r\ny  \n"
    once = normalize_whitespace(raw)
    assert once == normalize_whitespace(once)


def test_content_hash_stable_under_whitespace_changes() -> None:
    a = content_hash("# Title\n\nHello.\n")
    b = content_hash("# Title\n\n\n\nHello.   \n")
    assert a == b


def test_document_id_changes_with_url() -> None:
    a = document_id("/vercel/next.js", "https://example.com/a")
    b = document_id("/vercel/next.js", "https://example.com/b")
    assert a != b
    assert len(a) == 64
