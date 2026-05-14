"""Register / list / detail / refresh / delete routes."""

from __future__ import annotations

from typing import Any

import pytest
from doc_search_shared.db.tables import Job as JobRow
from doc_search_shared.db.tables import Library, LibraryAlias
from doc_search_shared.settings import Settings
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


def _register_payload(library_id: str = "/vercel/next.js") -> dict[str, Any]:
    return {
        "library_id": library_id,
        "name": "Next.js",
        "description": "React framework",
        "homepage_url": "https://nextjs.org",
        "doc_source": {
            "type": "github",
            "url": "https://github.com/vercel/next.js",
            "doc_paths": ["docs/**/*.md", "docs/**/*.mdx"],
        },
        "doc_type": "guide",
        "aliases": ["next", "nextjs"],
        "trust_score": 0.9,
        "profile": "light",
    }


def test_register_inserts_library_and_enqueues_full_job(
    client: TestClient,
    db_sessionmaker: sessionmaker[Session],
    sqs_client: Any,
    settings: Settings,
) -> None:
    resp = client.post("/libraries", json=_register_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["library_id"] == "/vercel/next.js"
    assert body["state"] == "queued"
    job_id = body["job_id"]

    with db_sessionmaker() as session:
        lib = session.execute(select(Library).where(Library.id == "/vercel/next.js")).scalar_one()
        assert lib.name == "Next.js"

        aliases = (
            session.execute(select(LibraryAlias.alias).where(LibraryAlias.library_id == lib.id))
            .scalars()
            .all()
        )
        assert {"next", "nextjs", "next.js"}.issubset(set(aliases))

        job_row = session.execute(select(JobRow).where(JobRow.job_id == job_id)).scalar_one()
        assert job_row.state == "queued"
        assert job_row.mode == "full"
        assert job_row.profile == "light"

    queue_url = sqs_client.get_queue_url(QueueName=settings.sqs_queue_light)["QueueUrl"]
    msgs = sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=0)
    assert msgs.get("Messages"), msgs


def test_register_invalid_library_id(client: TestClient) -> None:
    payload = _register_payload(library_id="vercel/next.js")  # missing leading slash
    resp = client.post("/libraries", json=payload)
    assert resp.status_code == 400


def test_register_conflict_returns_409(client: TestClient) -> None:
    client.post("/libraries", json=_register_payload())
    resp = client.post("/libraries", json=_register_payload())
    assert resp.status_code == 409


def test_list_libraries(client: TestClient) -> None:
    client.post("/libraries", json=_register_payload("/vercel/next.js"))
    client.post("/libraries", json=_register_payload("/tiangolo/fastapi"))
    resp = client.get("/libraries")
    assert resp.status_code == 200
    body = resp.json()
    ids = {row["library_id"] for row in body}
    assert ids == {"/vercel/next.js", "/tiangolo/fastapi"}


def test_get_library_returns_detail_with_recent_jobs(
    client: TestClient,
) -> None:
    client.post("/libraries", json=_register_payload())
    resp = client.get("/libraries/vercel/next.js")
    assert resp.status_code == 200
    body = resp.json()
    assert body["library_id"] == "/vercel/next.js"
    assert "next" in body["aliases"]
    assert len(body["recent_jobs"]) == 1
    assert body["recent_jobs"][0]["state"] == "queued"


def test_get_unknown_library_returns_404(client: TestClient) -> None:
    resp = client.get("/libraries/unknown/missing")
    assert resp.status_code == 404


def test_refresh_enqueues_incremental_by_default(
    client: TestClient,
    db_sessionmaker: sessionmaker[Session],
    sqs_client: Any,
    settings: Settings,
) -> None:
    client.post("/libraries", json=_register_payload())
    resp = client.post("/libraries/vercel/next.js/refresh")
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    with db_sessionmaker() as session:
        row = session.execute(select(JobRow).where(JobRow.job_id == job_id)).scalar_one()
        assert row.mode == "incremental"

    queue_url = sqs_client.get_queue_url(QueueName=settings.sqs_queue_light)["QueueUrl"]
    # Two jobs in queue: the register + the refresh.
    msgs = sqs_client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=0)
    assert len(msgs.get("Messages", [])) >= 1


def test_refresh_full_via_query_param(
    client: TestClient,
    db_sessionmaker: sessionmaker[Session],
) -> None:
    client.post("/libraries", json=_register_payload())
    resp = client.post("/libraries/vercel/next.js/refresh?mode=full")
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    with db_sessionmaker() as session:
        row = session.execute(select(JobRow).where(JobRow.job_id == job_id)).scalar_one()
        assert row.mode == "full"


def test_refresh_unknown_library_404(client: TestClient) -> None:
    resp = client.post("/libraries/unknown/missing/refresh")
    assert resp.status_code == 404


def test_versioned_refresh_route(
    client: TestClient,
    db_sessionmaker: sessionmaker[Session],
) -> None:
    payload = _register_payload(library_id="/vercel/next.js/v15.1.0")
    client.post("/libraries", json=payload)
    resp = client.post("/libraries/vercel/next.js/v15.1.0/refresh?mode=full")
    assert resp.status_code == 202
    with db_sessionmaker() as session:
        rows = (
            session.execute(select(JobRow).where(JobRow.library_id == "/vercel/next.js/v15.1.0"))
            .scalars()
            .all()
        )
        assert any(r.version == "v15.1.0" for r in rows)


def test_delete_removes_library(client: TestClient) -> None:
    client.post("/libraries", json=_register_payload())
    resp = client.delete("/libraries/vercel/next.js")
    assert resp.status_code == 204
    resp = client.get("/libraries/vercel/next.js")
    assert resp.status_code == 404


@pytest.mark.parametrize("path", ["/libraries/foo/bar", "/libraries/foo/bar/v1"])
def test_delete_missing_returns_404(client: TestClient, path: str) -> None:
    resp = client.delete(path)
    assert resp.status_code == 404
