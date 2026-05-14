"""S3 path helpers."""

from __future__ import annotations

import pytest
from doc_search_shared.s3 import artifact_path, markdown_path, raw_path


def test_raw_path_with_version() -> None:
    assert (
        raw_path("/vercel/next.js", "v15.1.0", "doc-abc", "html")
        == "raw/vercel/next.js/v15.1.0/doc-abc.html"
    )


def test_raw_path_without_version() -> None:
    assert (
        raw_path("/vercel/next.js", None, "doc-abc", "html")
        == "raw/vercel/next.js/_unversioned/doc-abc.html"
    )


def test_markdown_path() -> None:
    assert (
        markdown_path("/tiangolo/fastapi", "0.115.0", "doc-1")
        == "markdown/tiangolo/fastapi/0.115.0/doc-1.md"
    )


def test_artifact_path() -> None:
    assert (
        artifact_path("/a/b", "v1", "job-123", "report.json")
        == "artifacts/a/b/v1/job-123/report.json"
    )


def test_rejects_bad_library_id() -> None:
    with pytest.raises(ValueError):
        raw_path("vercel/next.js", "v1", "d")
