"""OpenAPI source: fetch the spec, fully deref ``$ref``, validate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from openapi_spec_validator import validate as validate_openapi

from ..logging_utils import log


@dataclass(slots=True)
class OpenapiSource:
    spec: dict[str, Any]
    raw_url: str


def fetch_and_resolve(url: str, *, timeout: float = 30.0) -> OpenapiSource:
    """Fetch a JSON/YAML OpenAPI doc, resolve internal ``$ref``s, validate."""
    log.info("openapi.fetch", url=url)
    raw = _fetch(url, timeout=timeout)
    parsed = _parse(raw)
    resolved = resolve_internal_refs(parsed)
    validate_openapi(resolved)
    return OpenapiSource(spec=resolved, raw_url=url)


def resolve_internal_refs(spec: dict[str, Any]) -> dict[str, Any]:
    """Deeply resolve every internal ``$ref: '#/...'`` to the referenced node.

    External refs (URLs/files) are left as-is. Cycles short-circuit to ``{}``.
    """
    result = _resolve(spec, spec, frozenset())
    if not isinstance(result, dict):
        raise ValueError("OpenAPI root must remain a mapping after $ref resolution")
    return result


def _fetch(url: str, *, timeout: float) -> str:
    if url.startswith(("http://", "https://")):
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    return Path(url).read_text(encoding="utf-8")


def _parse(text: str) -> dict[str, Any]:
    stripped = text.lstrip()
    data = json.loads(text) if stripped.startswith(("{", "[")) else yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("OpenAPI document must be a JSON/YAML mapping")
    return data


def _resolve(node: Any, root: dict[str, Any], visiting: frozenset[str]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            if ref in visiting:
                return {}
            target = _deref_pointer(root, ref[2:])
            return _resolve(target, root, visiting | {ref})
        return {k: _resolve(v, root, visiting) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(v, root, visiting) for v in node]
    return node


def _deref_pointer(root: dict[str, Any], pointer: str) -> Any:
    cur: Any = root
    for raw in pointer.split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


__all__ = ["OpenapiSource", "fetch_and_resolve", "resolve_internal_refs"]
