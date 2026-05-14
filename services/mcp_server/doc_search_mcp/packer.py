"""Token-budget packer for ``query_docs`` results.

Rules (from `phase-5.md`):

* Always include the top-scored chunk; if oversized, truncate while keeping
  ≥200 token headroom. The headroom is a *floor* on the truncated chunk so the
  user never gets a near-empty top match.
* Dedupe by ``section_id`` (chunks without one always pass).
* If ``include_examples=False``, strip fenced code blocks before counting and
  before emission.
* Greedy fill, but "keep scanning" — a single oversized chunk does not stop
  the loop; later, smaller chunks may still fit.
* Tokens count against ``tiktoken.cl100k_base``. A small ``Tokenizer``
  Protocol lets tests inject a deterministic char-based stand-in, since the
  real encoder downloads its BPE table on first use.
"""

from __future__ import annotations

import re
from typing import Protocol

from doc_search_shared.clients.rag_search_client import SearchHit
from pydantic import BaseModel, Field

# Lazy global tokenizer so `import packer` stays cheap and tests that inject
# their own tokenizer never trigger the tiktoken download.
_DEFAULT_TOKENIZER: Tokenizer | None = None

CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)

DEFAULT_HEADROOM_TOKENS = 200


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...
    def truncate(self, text: str, max_tokens: int) -> str: ...


class CL100KTokenizer:
    """Real tokenizer using ``tiktoken.cl100k_base``."""

    def __init__(self) -> None:
        import tiktoken

        self._enc = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        return len(self._enc.encode(text)) if text else 0

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        ids = self._enc.encode(text)
        if len(ids) <= max_tokens:
            return text
        return self._enc.decode(ids[:max_tokens])


class CharTokenizer:
    """Deterministic stand-in. ``ratio`` chars ≈ 1 token."""

    def __init__(self, ratio: int = 4) -> None:
        if ratio < 1:
            raise ValueError("ratio must be >= 1")
        self._ratio = ratio

    def count(self, text: str) -> int:
        if not text:
            return 0
        # Round up so non-empty strings always cost at least 1 token. This
        # mirrors tiktoken's behaviour on tiny inputs.
        return max(1, (len(text) + self._ratio - 1) // self._ratio)

    def truncate(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0 or not text:
            return ""
        return text[: max_tokens * self._ratio]


def get_default_tokenizer() -> Tokenizer:
    global _DEFAULT_TOKENIZER
    if _DEFAULT_TOKENIZER is None:
        _DEFAULT_TOKENIZER = CL100KTokenizer()
    return _DEFAULT_TOKENIZER


# --- Output models ------------------------------------------------------------


class PackedChunk(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    breadcrumbs: list[str] = Field(default_factory=list)
    source_url: str
    section_id: str | None = None
    score: float
    content: str
    tokens: int
    truncated: bool = False


class PackResult(BaseModel):
    chunks: list[PackedChunk] = Field(default_factory=list)
    tokens_used: int = 0
    truncated: bool = False


# --- Core packer --------------------------------------------------------------


def _strip_code_fences(text: str) -> str:
    return CODE_FENCE_RE.sub("", text).strip()


def _to_packed(hit: SearchHit, content: str, tokens: int, *, truncated: bool) -> PackedChunk:
    return PackedChunk(
        document_id=hit.document_id,
        chunk_id=hit.chunk_id,
        title=hit.title,
        breadcrumbs=hit.breadcrumbs,
        source_url=hit.source_url,
        section_id=hit.section_id,
        score=hit.score,
        content=content,
        tokens=tokens,
        truncated=truncated,
    )


def pack(
    hits: list[SearchHit],
    *,
    token_budget: int,
    include_examples: bool = True,
    tokenizer: Tokenizer | None = None,
    headroom: int = DEFAULT_HEADROOM_TOKENS,
) -> PackResult:
    """Pack ``hits`` into ``token_budget`` tokens following the Phase 5 rules."""
    if token_budget <= 0:
        return PackResult()
    if not hits:
        return PackResult()

    tk = tokenizer or get_default_tokenizer()
    sorted_hits = sorted(hits, key=lambda h: h.score, reverse=True)

    seen_sections: set[str] = set()
    packed: list[PackedChunk] = []
    overall_truncated = False

    # --- Top chunk: always included, optionally truncated ---
    top = sorted_hits[0]
    top_content = top.content if include_examples else _strip_code_fences(top.content)
    top_tokens = tk.count(top_content)
    top_truncated = False
    if top_tokens > token_budget:
        # Cap to the budget but never below the headroom floor — a 200-token
        # snippet is more useful than zero.
        target = max(token_budget, headroom)
        top_content = tk.truncate(top_content, target)
        top_tokens = tk.count(top_content)
        top_truncated = True
        overall_truncated = True

    packed.append(_to_packed(top, top_content, top_tokens, truncated=top_truncated))
    used = top_tokens
    if top.section_id:
        seen_sections.add(top.section_id)

    # --- Remaining: greedy + keep-scanning ---
    for hit in sorted_hits[1:]:
        if hit.section_id and hit.section_id in seen_sections:
            continue
        content = hit.content if include_examples else _strip_code_fences(hit.content)
        if not content:
            continue
        tokens = tk.count(content)
        if used + tokens > token_budget:
            overall_truncated = True
            continue
        packed.append(_to_packed(hit, content, tokens, truncated=False))
        used += tokens
        if hit.section_id:
            seen_sections.add(hit.section_id)

    return PackResult(chunks=packed, tokens_used=used, truncated=overall_truncated)


__all__ = [
    "DEFAULT_HEADROOM_TOKENS",
    "CL100KTokenizer",
    "CharTokenizer",
    "PackResult",
    "PackedChunk",
    "Tokenizer",
    "get_default_tokenizer",
    "pack",
]
