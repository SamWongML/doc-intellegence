"""OpenAPI source: fetch + ref resolution + validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from doc_search_worker.sources.openapi import fetch_and_resolve, resolve_internal_refs


def test_internal_refs_resolved(petstore_spec: dict[str, Any]) -> None:
    resolved = resolve_internal_refs(petstore_spec)
    pets_get = resolved["paths"]["/pets"]["get"]
    schema = pets_get["responses"]["200"]["content"]["application/json"]["schema"]
    # `Pets` is array of Pet — after resolution `items` is the Pet object, not a $ref.
    assert schema["type"] == "array"
    assert "$ref" not in schema["items"]
    assert schema["items"]["type"] == "object"
    assert "id" in schema["items"]["properties"]


def test_resolve_internal_refs_idempotent(petstore_spec: dict[str, Any]) -> None:
    once = resolve_internal_refs(petstore_spec)
    twice = resolve_internal_refs(once)
    # Same shape after second pass.
    assert (
        twice["paths"]["/pets"]["get"]["responses"]["200"]
        == once["paths"]["/pets"]["get"]["responses"]["200"]
    )


def test_fetch_and_resolve_local_file(tmp_path: Path, petstore_spec: dict[str, Any]) -> None:
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(petstore_spec), encoding="utf-8")
    src = fetch_and_resolve(str(p))
    assert src.raw_url == str(p)
    assert "/pets" in src.spec["paths"]
