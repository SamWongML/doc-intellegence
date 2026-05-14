"""OpenAPI operation parser."""

from __future__ import annotations

from typing import Any

from doc_search_worker.parsers.openapi import (
    OpenapiOperation,
    iter_operations,
    short_summary,
)


def test_iter_operations_yields_per_method_path(petstore_spec: dict[str, Any]) -> None:
    ops = list(iter_operations(petstore_spec))
    routes = {(o.method, o.path) for o in ops}
    assert routes == {
        ("GET", "/pets"),
        ("POST", "/pets"),
        ("GET", "/pets/{petId}"),
    }


def test_markdown_body_includes_required_sections(petstore_spec: dict[str, Any]) -> None:
    ops = list(iter_operations(petstore_spec))
    list_pets = next(o for o in ops if o.operation_id == "listPets")
    md = list_pets.markdown
    assert md.startswith("# GET /pets")
    assert "## Parameters" in md
    assert "## Request body" in md
    assert "## Responses" in md
    assert "## Security" in md
    assert "| limit | query | integer | no |" in md


def test_security_section_lists_schemes(petstore_spec: dict[str, Any]) -> None:
    ops = list(iter_operations(petstore_spec))
    create = next(o for o in ops if o.operation_id == "createPets")
    assert "- `apiKey`" in create.markdown


def test_short_summary_truncates() -> None:
    op = OpenapiOperation(
        method="GET",
        path="/x",
        summary="word " * 100,  # ~500 chars
        description="",
        operation_id=None,
    )
    s = short_summary(op)
    assert len(s) <= 200


def test_operation_keeps_full_spec(petstore_spec: dict[str, Any]) -> None:
    ops = list(iter_operations(petstore_spec))
    get_pet = next(o for o in ops if o.path == "/pets/{petId}")
    assert get_pet.spec["operationId"] == "showPetById"
    # `parameters` from path-level + op-level merged on the OpenapiOperation,
    # but spec itself preserves the original op block.
    assert "responses" in get_pet.spec
