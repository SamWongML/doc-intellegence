"""Markdown parser: AST extraction + canonical body emission.

Per phase-1: mistune parses to AST; python-frontmatter strips/loads the YAML
frontmatter; we normalize the body (bullets → `-`, fenced code lang hint,
collapsed blank lines) to a canonical Markdown string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import frontmatter
import mistune

from ..enrich.code_blocks import language_from_info

_BULLET = re.compile(r"^(\s*)[*+](\s+)", re.MULTILINE)
_BLANK_RUN = re.compile(r"\n{3,}")
_FENCE = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)$", re.MULTILINE)


@dataclass
class MarkdownDoc:
    """Result of parsing one Markdown/MDX file."""

    title: str
    metadata: dict[str, Any] = field(default_factory=dict)
    headings: list[tuple[int, str]] = field(default_factory=list)
    code_languages: list[str] = field(default_factory=list)
    canonical: str = ""


def parse_markdown(content: str, *, default_title: str = "Untitled") -> MarkdownDoc:
    """Parse a Markdown/MDX document. Returns title, headings, code langs,
    canonical body, and frontmatter metadata."""
    post = frontmatter.loads(content)
    body = post.content
    metadata: dict[str, Any] = dict(post.metadata)

    tokens = _tokenize(body)
    headings: list[tuple[int, str]] = []
    code_langs: list[str] = []
    _walk(tokens, headings, code_langs)

    title = _resolve_title(metadata, headings, default_title)
    canonical = _normalize_body(body)
    return MarkdownDoc(
        title=title,
        metadata=metadata,
        headings=headings,
        code_languages=code_langs,
        canonical=canonical,
    )


def _tokenize(body: str) -> list[dict[str, Any]]:
    md = mistune.create_markdown(renderer=None)
    result: Any = md(body)
    if isinstance(result, tuple):
        result = result[0]
    if not isinstance(result, list):
        return []
    return [t for t in result if isinstance(t, dict)]


def _walk(
    tokens: list[dict[str, Any]],
    headings: list[tuple[int, str]],
    code_langs: list[str],
) -> None:
    for tok in tokens:
        ttype = tok.get("type")
        if ttype == "heading":
            level = int(tok.get("attrs", {}).get("level", 1))
            headings.append((level, _flatten(tok.get("children"))))
        elif ttype in ("block_code", "fenced_code"):
            info = tok.get("attrs", {}).get("info") or ""
            lang = language_from_info(info)
            if lang:
                code_langs.append(lang)
        children = tok.get("children")
        if isinstance(children, list):
            _walk(
                [c for c in children if isinstance(c, dict)],
                headings,
                code_langs,
            )


def _flatten(children: list[dict[str, Any]] | None) -> str:
    if not children:
        return ""
    parts: list[str] = []
    for c in children:
        raw = c.get("raw")
        if isinstance(raw, str):
            parts.append(raw)
        elif isinstance(c.get("children"), list):
            parts.append(_flatten(c["children"]))
    return "".join(parts).strip()


def _resolve_title(
    metadata: dict[str, Any],
    headings: list[tuple[int, str]],
    default: str,
) -> str:
    md_title = metadata.get("title")
    if isinstance(md_title, str) and md_title.strip():
        return md_title.strip()
    for level, text in headings:
        if level == 1 and text:
            return text
    return headings[0][1] if headings else default


def _normalize_body(body: str) -> str:
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = _normalize_bullets(body)
    body = "\n".join(line.rstrip() for line in body.split("\n"))
    body = _BLANK_RUN.sub("\n\n", body)
    return body.strip() + "\n"


def _normalize_bullets(body: str) -> str:
    """Rewrite `*`/`+` bullet markers to `-`, but skip lines inside fenced code."""
    fences = list(_FENCE.finditer(body))
    if not fences:
        return _BULLET.sub(r"\1-\2", body)

    out: list[str] = []
    cursor = 0
    in_code = False
    open_fence: str | None = None
    for match in fences:
        chunk = body[cursor : match.start()]
        out.append(_BULLET.sub(r"\1-\2", chunk) if not in_code else chunk)
        out.append(match.group(0))
        fence = match.group("fence")
        if not in_code:
            in_code = True
            open_fence = fence
        elif open_fence and fence.startswith(open_fence[0]) and len(fence) >= len(open_fence):
            in_code = False
            open_fence = None
        cursor = match.end()
    tail = body[cursor:]
    out.append(_BULLET.sub(r"\1-\2", tail) if not in_code else tail)
    return "".join(out)


__all__ = ["MarkdownDoc", "parse_markdown"]
