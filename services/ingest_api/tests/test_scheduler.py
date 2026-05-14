"""EventBridge Scheduler upsert/delete via moto."""

from __future__ import annotations

from typing import Any

import pytest
from doc_search_ingest.scheduler import SchedulerClient
from doc_search_shared.models import JobSource
from doc_search_shared.settings import Settings


def test_scheduler_no_op_when_arns_unset(scheduler_client: Any) -> None:
    settings = Settings(scheduler_role_arn=None, scheduler_target_arn=None)
    sc = SchedulerClient(scheduler=scheduler_client, settings=settings)
    assert sc.is_enabled() is False
    name = sc.upsert_refresh_schedule(
        library_id="/vercel/next.js",
        version=None,
        source=JobSource(
            type="github",
            url="https://github.com/vercel/next.js",
            doc_paths=["docs/**/*.md"],
        ),
    )
    assert name is None


def test_scheduler_create_and_update(scheduler_client: Any, settings: Settings) -> None:
    sc = SchedulerClient(scheduler=scheduler_client, settings=settings)
    source = JobSource(
        type="github",
        url="https://github.com/vercel/next.js",
        doc_paths=["docs/**/*.md"],
    )
    name = sc.upsert_refresh_schedule(library_id="/vercel/next.js", version=None, source=source)
    assert name == "ds-vercel-next_js"
    listed = scheduler_client.list_schedules(GroupName=settings.scheduler_group_name)
    assert any(s["Name"] == name for s in listed.get("Schedules", []))

    # Updating same library_id should not error.
    name2 = sc.upsert_refresh_schedule(
        library_id="/vercel/next.js",
        version=None,
        source=source,
        schedule_expression="cron(0 12 * * ? *)",
    )
    assert name2 == name


def test_scheduler_delete(scheduler_client: Any, settings: Settings) -> None:
    sc = SchedulerClient(scheduler=scheduler_client, settings=settings)
    source = JobSource(
        type="github",
        url="https://github.com/vercel/next.js",
        doc_paths=["docs/**/*.md"],
    )
    sc.upsert_refresh_schedule(library_id="/vercel/next.js", version=None, source=source)
    sc.delete_refresh_schedule("/vercel/next.js")
    listed = scheduler_client.list_schedules(GroupName=settings.scheduler_group_name)
    assert not any(s["Name"].startswith("ds-vercel-next") for s in listed.get("Schedules", []))


def test_scheduler_delete_unknown_is_silent(scheduler_client: Any, settings: Settings) -> None:
    sc = SchedulerClient(scheduler=scheduler_client, settings=settings)
    sc.delete_refresh_schedule("/never/registered")  # no exception


def test_register_route_creates_schedule(
    client: Any, scheduler_client: Any, settings: Settings
) -> None:
    payload = {
        "library_id": "/vercel/next.js",
        "name": "Next.js",
        "doc_source": {
            "type": "github",
            "url": "https://github.com/vercel/next.js",
            "doc_paths": ["docs/**/*.md"],
        },
        "refresh_schedule": "cron(0 6 * * ? *)",
    }
    resp = client.post("/libraries", json=payload)
    assert resp.status_code == 201
    listed = scheduler_client.list_schedules(GroupName=settings.scheduler_group_name)
    names = [s["Name"] for s in listed.get("Schedules", [])]
    assert any(n.startswith("ds-vercel-next") for n in names), names


@pytest.mark.parametrize(
    ("library_id", "expected_prefix"),
    [
        ("/vercel/next.js", "ds-vercel-next"),
        ("/tiangolo/fastapi", "ds-tiangolo-fastapi"),
    ],
)
def test_scheduler_name_safe(
    scheduler_client: Any,
    settings: Settings,
    library_id: str,
    expected_prefix: str,
) -> None:
    sc = SchedulerClient(scheduler=scheduler_client, settings=settings)
    source = JobSource(
        type="github",
        url=f"https://github.com{library_id}",
        doc_paths=["docs/**/*.md"],
    )
    name = sc.upsert_refresh_schedule(library_id=library_id, version=None, source=source)
    assert name is not None and name.startswith(expected_prefix)
