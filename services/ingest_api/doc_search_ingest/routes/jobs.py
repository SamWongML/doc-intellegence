"""Job status route."""

from __future__ import annotations

from doc_search_shared.db.tables import Job as JobRow
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from ..deps import SessionDep, authenticated_and_limited
from ..schemas import JobSummary

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
    dependencies=[Depends(authenticated_and_limited)],
)


@router.get("/{job_id}", response_model=JobSummary)
def get_job(job_id: str, session: SessionDep) -> JobSummary:
    row = session.execute(select(JobRow).where(JobRow.job_id == job_id)).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"job not found: {job_id}",
        )
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


__all__ = ["router"]
