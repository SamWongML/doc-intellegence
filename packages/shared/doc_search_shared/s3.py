"""S3 key/path helpers.

Layout::

    raw/<library_id>/<version>/<document_id>.<ext>
    markdown/<library_id>/<version>/<document_id>.md
    artifacts/<library_id>/<version>/<job_id>/<name>
"""

from __future__ import annotations

from .ids import parse_library_id

_NO_VERSION = "_unversioned"


def _safe_lib(library_id: str) -> str:
    parse_library_id(library_id)
    return library_id.lstrip("/")


def _version(version: str | None) -> str:
    return version or _NO_VERSION


def raw_path(library_id: str, version: str | None, document_id: str, ext: str = "html") -> str:
    return f"raw/{_safe_lib(library_id)}/{_version(version)}/{document_id}.{ext.lstrip('.')}"


def markdown_path(library_id: str, version: str | None, document_id: str) -> str:
    return f"markdown/{_safe_lib(library_id)}/{_version(version)}/{document_id}.md"


def artifact_path(library_id: str, version: str | None, job_id: str, name: str) -> str:
    return f"artifacts/{_safe_lib(library_id)}/{_version(version)}/{job_id}/{name}"


__all__ = ["artifact_path", "markdown_path", "raw_path"]
