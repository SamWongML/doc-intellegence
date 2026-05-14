"""OpenAPI operation parser.

One `(method, path)` → one ``ProcessedDocument``. Body template per phase-1:

    # POST /users/{id}
    > {summary}
    ## Parameters
    | name | in | type | required | description |
    ## Request body
    ## Responses
    ## Security
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

_METHODS: tuple[str, ...] = (
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "trace",
)


@dataclass(slots=True)
class OpenapiOperation:
    method: str
    path: str
    summary: str
    description: str
    operation_id: str | None
    tags: list[str] = field(default_factory=list)
    markdown: str = ""
    spec: dict[str, Any] = field(default_factory=dict)


def iter_operations(spec: dict[str, Any]) -> Iterator[OpenapiOperation]:
    """Yield one ``OpenapiOperation`` per ``(method, path)`` in ``spec.paths``."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return
    for path, item in paths.items():
        if not isinstance(item, dict):
            continue
        shared_params = list(item.get("parameters") or [])
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            op_params = list(op.get("parameters") or [])
            yield _build_operation(method, str(path), op, shared_params + op_params)


def short_summary(op: OpenapiOperation) -> str:
    """First 200 chars of the operation summary (or method+path stub)."""
    base = op.summary or op.description or f"{op.method} {op.path}"
    return _truncate(" ".join(base.split()), 200)


def _build_operation(
    method: str,
    path: str,
    op: dict[str, Any],
    params: list[dict[str, Any]],
) -> OpenapiOperation:
    summary = str(op.get("summary") or "").strip()
    description = str(op.get("description") or "").strip()
    raw_op_id = op.get("operationId")
    op_id = str(raw_op_id) if isinstance(raw_op_id, str) and raw_op_id.strip() else None
    tags = [str(t) for t in (op.get("tags") or []) if isinstance(t, str)]
    body_md = _render(method, path, summary, description, op, params)
    return OpenapiOperation(
        method=method.upper(),
        path=path,
        summary=summary,
        description=description,
        operation_id=op_id,
        tags=tags,
        markdown=body_md,
        spec=op,
    )


def _render(
    method: str,
    path: str,
    summary: str,
    description: str,
    op: dict[str, Any],
    params: list[dict[str, Any]],
) -> str:
    lines: list[str] = [f"# {method.upper()} {path}"]
    if summary:
        lines += ["", f"> {_one_line(summary)}"]
    if description and description != summary:
        lines += ["", description.strip()]

    lines += ["", "## Parameters", ""]
    if params:
        lines.append("| name | in | type | required | description |")
        lines.append("| --- | --- | --- | --- | --- |")
        for p in params:
            lines.append(
                "| {name} | {loc} | {type} | {req} | {desc} |".format(
                    name=_one_line(str(p.get("name", ""))),
                    loc=_one_line(str(p.get("in", ""))),
                    type=_param_type(p),
                    req="yes" if p.get("required") else "no",
                    desc=_one_line(str(p.get("description", ""))),
                )
            )
    else:
        lines.append("_None._")

    lines += ["", "## Request body", ""]
    body = op.get("requestBody")
    if isinstance(body, dict):
        required = "required" if body.get("required") else "optional"
        media = sorted((body.get("content") or {}).keys())
        media_str = ", ".join(media) if media else "n/a"
        lines.append(f"_{required}_ — media: {media_str}")
        rb_desc = str(body.get("description") or "").strip()
        if rb_desc:
            lines += ["", _one_line(rb_desc)]
    else:
        lines.append("_None._")

    lines += ["", "## Responses", ""]
    responses = op.get("responses")
    if isinstance(responses, dict) and responses:
        lines.append("| status | description |")
        lines.append("| --- | --- |")
        for status, resp in responses.items():
            r_desc = ""
            if isinstance(resp, dict):
                r_desc = _one_line(str(resp.get("description") or ""))
            lines.append(f"| {status} | {r_desc} |")
    else:
        lines.append("_None._")

    lines += ["", "## Security", ""]
    security = op.get("security")
    if isinstance(security, list) and security:
        for entry in security:
            if not isinstance(entry, dict):
                continue
            for scheme, scopes in entry.items():
                scope_str = (
                    ", ".join(scopes) if isinstance(scopes, list) and scopes else "_no scopes_"
                )
                lines.append(f"- `{scheme}`: {scope_str}")
    else:
        lines.append("_None._")
    lines.append("")
    return "\n".join(lines)


def _param_type(p: dict[str, Any]) -> str:
    schema = p.get("schema")
    if isinstance(schema, dict):
        t = schema.get("type")
        if isinstance(t, str):
            return t
    t2 = p.get("type")
    return t2 if isinstance(t2, str) else "any"


def _one_line(s: str) -> str:
    return " ".join(s.split())


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


__all__ = ["OpenapiOperation", "iter_operations", "short_summary"]
