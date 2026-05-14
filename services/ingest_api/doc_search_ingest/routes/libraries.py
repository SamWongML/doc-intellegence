"""Library register / list / detail / refresh / delete routes.

Library IDs are path-like ``/org/project[/version]``. URL paths can't carry
slashes inside a single path-param, so the routes here decompose the id into
``org / project / [version]`` segments. The handler reassembles the id and
validates via :func:`doc_search_shared.ids.parse_library_id`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from doc_search_shared.db.tables import (
    Job as JobRow,
)
from doc_search_shared.db.tables import (
    Library,
    LibraryAlias,
    LibraryVersion,
)
from doc_search_shared.ids import parse_library_id
from doc_search_shared.models import JobSource, Mode
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..deps import (
    PrincipalDep,
    PublisherDep,
    SchedulerDep,
    SessionDep,
    authenticated_and_limited,
)
from ..publisher import JobPublisher
from ..scheduler import SchedulerClient
from ..schemas import (
    EnqueueResponse,
    JobSummary,
    LibraryDetail,
    LibrarySummary,
    RegisterLibraryRequest,
)

router = APIRouter(
    prefix="/libraries",
    tags=["libraries"],
    dependencies=[Depends(authenticated_and_limited)],
)

ModeQuery = Annotated[Literal["full", "incremental"], Query()]


def _make_id(org: str, project: str, version: str | None = None) -> str:
    parts = [org, project] + ([version] if version else [])
    library_id = "/" + "/".join(parts)
    try:
        return parse_library_id(library_id).id
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _library_row(session: Session, library_id: str) -> Library:
    row = session.execute(select(Library).where(Library.id == library_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"library not found: {library_id}",
        )
    return row


def _summary(row: Library) -> LibrarySummary:
    return LibrarySummary(
        library_id=row.id,
        name=row.name,
        description=row.description,
        homepage_url=row.homepage_url,
        doc_type=row.doc_type,
        latest_version=row.latest_version,
        last_indexed_at=row.last_indexed_at,
        chunk_count=row.chunk_count,
        trust_score=row.trust_score,
    )


def _job_summary(row: JobRow) -> JobSummary:
    return JobSummary(
        job_id=row.job_id,
        library_id=row.library_id,
        version=row.version,
        state=row.state,
        mode=row.mode,
        profile=row.profile,
        docs_total=row.docs_total,
        docs_processed=row.docs_processed,
        docs_failed=row.docs_failed,
        error=row.error,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
    )


@router.post(
    "",
    response_model=EnqueueResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_library(
    body: RegisterLibraryRequest,
    session: SessionDep,
    publisher: PublisherDep,
    scheduler: SchedulerDep,
    principal: PrincipalDep,
) -> EnqueueResponse:
    try:
        ref = parse_library_id(body.library_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    existing = session.execute(select(Library).where(Library.id == ref.id)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"library already exists: {ref.id}",
        )

    now = datetime.now(UTC)
    session.add(
        Library(
            id=ref.id,
            name=body.name,
            org=ref.org,
            project=ref.project,
            description=body.description,
            homepage_url=body.homepage_url,
            doc_source=body.doc_source.model_dump(),
            trust_score=body.trust_score,
            doc_type=body.doc_type,
            latest_version=ref.version,
            created_at=now,
            updated_at=now,
        )
    )
    for alias in {*body.aliases, ref.project}:
        session.add(LibraryAlias(alias=alias, library_id=ref.id))
    if ref.version:
        session.add(
            LibraryVersion(
                library_id=ref.id,
                version=ref.version,
                is_latest=True,
            )
        )

    job = publisher.enqueue(
        session=session,
        library_id=ref.id,
        version=ref.version,
        source=body.doc_source,
        mode="full",
        profile=body.profile,
        requested_by=principal,
    )

    scheduler.upsert_refresh_schedule(
        library_id=ref.id,
        version=ref.version,
        source=body.doc_source,
        schedule_expression=body.refresh_schedule,
    )

    session.commit()
    return EnqueueResponse(job_id=job.job_id, library_id=ref.id)


@router.get("", response_model=list[LibrarySummary])
def list_libraries(session: SessionDep) -> list[LibrarySummary]:
    rows = session.execute(select(Library).order_by(Library.id)).scalars().all()
    return [_summary(r) for r in rows]


def _refresh(
    *,
    org: str,
    project: str,
    version: str | None,
    mode: Mode,
    session: Session,
    publisher: JobPublisher,
    principal: str,
) -> EnqueueResponse:
    library_id = _make_id(org, project, version)
    row = _library_row(session, library_id)
    source = row.doc_source or {}
    job_source = JobSource.model_validate(source)
    job = publisher.enqueue(
        session=session,
        library_id=library_id,
        version=version,
        source=job_source,
        mode=mode,
        profile="light",
        requested_by=principal,
    )
    session.commit()
    return EnqueueResponse(job_id=job.job_id, library_id=library_id)


@router.post(
    "/{org}/{project}/refresh",
    response_model=EnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_library(
    org: str,
    project: str,
    session: SessionDep,
    publisher: PublisherDep,
    principal: PrincipalDep,
    mode: ModeQuery = "incremental",
) -> EnqueueResponse:
    return _refresh(
        org=org,
        project=project,
        version=None,
        mode=mode,
        session=session,
        publisher=publisher,
        principal=principal,
    )


@router.post(
    "/{org}/{project}/{version}/refresh",
    response_model=EnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_library_versioned(
    org: str,
    project: str,
    version: str,
    session: SessionDep,
    publisher: PublisherDep,
    principal: PrincipalDep,
    mode: ModeQuery = "incremental",
) -> EnqueueResponse:
    return _refresh(
        org=org,
        project=project,
        version=version,
        mode=mode,
        session=session,
        publisher=publisher,
        principal=principal,
    )


def _detail(
    *,
    org: str,
    project: str,
    version: str | None,
    session: Session,
) -> LibraryDetail:
    library_id = _make_id(org, project, version)
    row = _library_row(session, library_id)
    aliases = (
        session.execute(select(LibraryAlias.alias).where(LibraryAlias.library_id == library_id))
        .scalars()
        .all()
    )
    versions = (
        session.execute(
            select(LibraryVersion.version)
            .where(LibraryVersion.library_id == library_id)
            .order_by(LibraryVersion.version)
        )
        .scalars()
        .all()
    )
    recent = (
        session.execute(
            select(JobRow)
            .where(JobRow.library_id == library_id)
            .order_by(desc(JobRow.created_at))
            .limit(10)
        )
        .scalars()
        .all()
    )
    summary = _summary(row)
    return LibraryDetail(
        **summary.model_dump(),
        aliases=sorted(aliases),
        versions=list(versions),
        recent_jobs=[_job_summary(j) for j in recent],
    )


@router.get("/{org}/{project}", response_model=LibraryDetail)
def get_library(org: str, project: str, session: SessionDep) -> LibraryDetail:
    return _detail(org=org, project=project, version=None, session=session)


@router.get("/{org}/{project}/{version}", response_model=LibraryDetail)
def get_library_versioned(
    org: str,
    project: str,
    version: str,
    session: SessionDep,
) -> LibraryDetail:
    return _detail(org=org, project=project, version=version, session=session)


def _delete(
    *,
    org: str,
    project: str,
    version: str | None,
    session: Session,
    scheduler: SchedulerClient,
) -> None:
    library_id = _make_id(org, project, version)
    row = _library_row(session, library_id)
    session.delete(row)
    scheduler.delete_refresh_schedule(library_id)
    session.commit()


@router.delete("/{org}/{project}", status_code=status.HTTP_204_NO_CONTENT)
def delete_library(
    org: str,
    project: str,
    session: SessionDep,
    scheduler: SchedulerDep,
) -> None:
    _delete(
        org=org,
        project=project,
        version=None,
        session=session,
        scheduler=scheduler,
    )


@router.delete("/{org}/{project}/{version}", status_code=status.HTTP_204_NO_CONTENT)
def delete_library_versioned(
    org: str,
    project: str,
    version: str,
    session: SessionDep,
    scheduler: SchedulerDep,
) -> None:
    _delete(
        org=org,
        project=project,
        version=version,
        session=session,
        scheduler=scheduler,
    )


__all__ = ["router"]
