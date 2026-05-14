"""Detect language tags from fenced code block info strings."""

from __future__ import annotations

import re
from collections.abc import Iterable

_LANG_TOKEN = re.compile(r"^([A-Za-z0-9_+.#-]+)")


def language_from_info(info: str | None) -> str | None:
    """Extract the language token from a fenced-code info string (`bash {numbered}`)."""
    if not info:
        return None
    match = _LANG_TOKEN.match(info.strip())
    return match.group(1).lower() if match else None


def dedupe_tags(langs: Iterable[str | None]) -> list[str]:
    """Preserve first-seen order; drop falsy entries."""
    out: list[str] = []
    seen: set[str] = set()
    for lang in langs:
        if not lang:
            continue
        if lang not in seen:
            seen.add(lang)
            out.append(lang)
    return out


__all__ = ["dedupe_tags", "language_from_info"]
