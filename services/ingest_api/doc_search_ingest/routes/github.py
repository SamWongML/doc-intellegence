"""GitHub webhook endpoint.

HMAC-verifies the body, parses the push event, and enqueues an incremental
refresh per matching library.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status

from ..deps import PublisherDep, SessionDep, SettingsDep
from ..schemas import WebhookResponse
from ..webhooks import (
    extract_push_paths,
    job_source_from_library,
    libraries_for_repo,
    matches_doc_paths,
    normalize_repo_url,
    verify_signature,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    settings: SettingsDep,
    session: SessionDep,
    publisher: PublisherDep,
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
    x_github_event: Annotated[str | None, Header(alias="X-GitHub-Event")] = None,
) -> WebhookResponse:
    body = await request.body()
    if not verify_signature(
        body=body, header=x_hub_signature_256, secret=settings.github_webhook_secret
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid signature")

    if x_github_event == "ping":
        return WebhookResponse(accepted=True, reason="pong")
    if x_github_event != "push":
        return WebhookResponse(accepted=True, reason="ignored non-push event")

    try:
        event = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid json: {exc}"
        ) from exc

    repo = event.get("repository") or {}
    repo_full = repo.get("full_name") or normalize_repo_url(
        repo.get("clone_url") or repo.get("html_url") or ""
    )
    if not repo_full:
        return WebhookResponse(accepted=True, reason="no repository field")
    repo_full = repo_full.lower()

    libs = libraries_for_repo(session, repo_full_name=repo_full)
    if not libs:
        return WebhookResponse(accepted=True, reason="no matching library")

    changed = extract_push_paths(event)
    enqueued: list[str] = []
    for lib in libs:
        source = job_source_from_library(lib)
        if not matches_doc_paths(changed, source.doc_paths):
            continue
        job = publisher.enqueue(
            session=session,
            library_id=lib.id,
            version=lib.latest_version,
            source=source,
            mode="incremental",
            profile="light",
            requested_by="github-webhook",
        )
        enqueued.append(job.job_id)
    session.commit()
    return WebhookResponse(accepted=True, enqueued_jobs=enqueued)


__all__ = ["router"]
