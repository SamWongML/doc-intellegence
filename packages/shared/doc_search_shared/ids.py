"""ID helpers: ULID generation and `library_id` parsing.

A `library_id` is a path-like string: ``/org/project`` or ``/org/project/version``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ulid import ULID

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def new_ulid() -> str:
    """Return a fresh ULID as a 26-char Crockford base32 string."""
    return str(ULID())


@dataclass(frozen=True, slots=True)
class LibraryRef:
    org: str
    project: str
    version: str | None = None

    @property
    def id(self) -> str:
        if self.version:
            return f"/{self.org}/{self.project}/{self.version}"
        return f"/{self.org}/{self.project}"


def parse_library_id(library_id: str) -> LibraryRef:
    """Parse ``/org/project`` or ``/org/project/version``.

    Raises ``ValueError`` on any malformed input.
    """
    if not library_id.startswith("/"):
        raise ValueError(f"library_id must start with '/': {library_id!r}")
    parts = library_id[1:].split("/")
    if len(parts) not in (2, 3):
        raise ValueError(f"library_id must be /org/project or /org/project/version: {library_id!r}")
    for segment in parts:
        if not segment or not _SEGMENT_RE.match(segment):
            raise ValueError(f"invalid segment {segment!r} in {library_id!r}")
    return LibraryRef(
        org=parts[0],
        project=parts[1],
        version=parts[2] if len(parts) == 3 else None,
    )


def validate_library_id(library_id: str) -> str:
    """Validate and return canonical ``library_id`` (raises ``ValueError`` if bad)."""
    return parse_library_id(library_id).id


__all__ = ["LibraryRef", "new_ulid", "parse_library_id", "validate_library_id"]
