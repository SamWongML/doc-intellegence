"""ID helpers."""

from __future__ import annotations

import pytest
from doc_search_shared.ids import (
    new_ulid,
    parse_library_id,
    validate_library_id,
)


def test_new_ulid_length_and_uniqueness() -> None:
    a = new_ulid()
    b = new_ulid()
    assert len(a) == 26
    assert len(b) == 26
    assert a != b


def test_parse_library_id_two_segments() -> None:
    ref = parse_library_id("/vercel/next.js")
    assert ref.org == "vercel"
    assert ref.project == "next.js"
    assert ref.version is None
    assert ref.id == "/vercel/next.js"


def test_parse_library_id_three_segments() -> None:
    ref = parse_library_id("/vercel/next.js/v15.1.0")
    assert ref.org == "vercel"
    assert ref.project == "next.js"
    assert ref.version == "v15.1.0"
    assert ref.id == "/vercel/next.js/v15.1.0"


@pytest.mark.parametrize(
    "bad",
    [
        "vercel/next.js",  # missing leading slash
        "/vercel",  # too few
        "/vercel/next/15/extra",  # too many
        "/vercel//v15",  # empty segment
        "/vercel/next$/v15",  # invalid char
        "/",  # empty
    ],
)
def test_parse_library_id_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_library_id(bad)


def test_validate_library_id_returns_canonical() -> None:
    assert validate_library_id("/a/b") == "/a/b"
    assert validate_library_id("/a/b/c") == "/a/b/c"
