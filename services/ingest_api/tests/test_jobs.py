"""GET /jobs/{job_id}."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _register(client: TestClient) -> str:
    payload = {
        "library_id": "/vercel/next.js",
        "name": "Next.js",
        "doc_source": {
            "type": "github",
            "url": "https://github.com/vercel/next.js",
            "doc_paths": ["docs/**/*.md"],
        },
    }
    resp = client.post("/libraries", json=payload)
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    job_id: str = body["job_id"]
    return job_id


def test_get_job_returns_queued_state(client: TestClient) -> None:
    job_id = _register(client)
    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["state"] == "queued"
    assert body["library_id"] == "/vercel/next.js"


def test_get_unknown_job_404(client: TestClient) -> None:
    resp = client.get("/jobs/01H000000000000000000NOPE")
    assert resp.status_code == 404
