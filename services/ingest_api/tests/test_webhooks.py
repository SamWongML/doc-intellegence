"""GitHub webhook: signature verification + push handling."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from doc_search_shared.settings import Settings
from fastapi.testclient import TestClient


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _push_event(
    full_name: str = "vercel/next.js",
    paths: list[str] | None = None,
) -> dict[str, Any]:
    paths = paths or ["docs/app-router/routing.mdx"]
    return {
        "ref": "refs/heads/main",
        "repository": {
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "clone_url": f"https://github.com/{full_name}.git",
        },
        "commits": [{"added": [], "modified": paths, "removed": []}],
    }


def _register(client: TestClient) -> None:
    payload = {
        "library_id": "/vercel/next.js",
        "name": "Next.js",
        "doc_source": {
            "type": "github",
            "url": "https://github.com/vercel/next.js",
            "doc_paths": ["docs/**/*.mdx"],
        },
    }
    resp = client.post("/libraries", json=payload)
    assert resp.status_code == 201, resp.text


def test_webhook_rejects_bad_signature(client: TestClient, settings: Settings) -> None:
    body = json.dumps(_push_event()).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Event": "push",
        },
    )
    assert resp.status_code == 401


def test_webhook_ping_pong(client: TestClient, settings: Settings) -> None:
    body = b"{}"
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, settings.github_webhook_secret),
            "X-GitHub-Event": "ping",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["reason"] == "pong"


def test_webhook_push_enqueues_refresh(
    client: TestClient,
    settings: Settings,
    sqs_client: Any,
) -> None:
    _register(client)
    queue_url = sqs_client.get_queue_url(QueueName=settings.sqs_queue_light)["QueueUrl"]

    def depth() -> int:
        attrs = sqs_client.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages"]
        )
        return int(attrs["Attributes"]["ApproximateNumberOfMessages"])

    before = depth()

    body = json.dumps(_push_event()).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, settings.github_webhook_secret),
            "X-GitHub-Event": "push",
        },
    )
    assert resp.status_code == 200, resp.text
    body_out = resp.json()
    assert body_out["accepted"] is True
    assert len(body_out["enqueued_jobs"]) == 1

    assert depth() == before + 1


def test_webhook_push_ignores_paths_outside_doc_paths(
    client: TestClient, settings: Settings
) -> None:
    _register(client)
    body = json.dumps(_push_event(paths=["src/foo.ts"])).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, settings.github_webhook_secret),
            "X-GitHub-Event": "push",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["enqueued_jobs"] == []


def test_webhook_push_unknown_repo(client: TestClient, settings: Settings) -> None:
    body = json.dumps(_push_event(full_name="someone/else")).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, settings.github_webhook_secret),
            "X-GitHub-Event": "push",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["enqueued_jobs"] == []


def test_webhook_ignored_event_type(client: TestClient, settings: Settings) -> None:
    body = b"{}"
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, settings.github_webhook_secret),
            "X-GitHub-Event": "issues",
        },
    )
    assert resp.status_code == 200
    assert "ignored" in (resp.json()["reason"] or "")
