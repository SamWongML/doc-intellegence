"""Initial schema (contracts.md §E).

Revision ID: 20260514_0001
Revises:
Create Date: 2026-05-14

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "libraries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("org", sa.Text(), nullable=False),
        sa.Column("project", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("homepage_url", sa.Text()),
        sa.Column("doc_source", postgresql.JSONB()),
        sa.Column("trust_score", sa.REAL(), server_default=sa.text("0.5")),
        sa.Column("doc_type", sa.Text()),
        sa.Column("latest_version", sa.Text()),
        sa.Column("last_indexed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    op.create_table(
        "library_aliases",
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column(
            "library_id",
            sa.Text(),
            sa.ForeignKey("libraries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("alias", "library_id"),
    )
    op.execute(
        "CREATE INDEX ix_aliases_alias_lower ON library_aliases (LOWER(alias))"
    )

    op.create_table(
        "library_versions",
        sa.Column(
            "library_id",
            sa.Text(),
            sa.ForeignKey("libraries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), server_default=sa.text("FALSE")),
        sa.Column("indexed_at", sa.TIMESTAMP(timezone=True)),
        sa.PrimaryKeyConstraint("library_id", "version"),
    )

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("library_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Text()),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("source", postgresql.JSONB(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("docs_total", sa.Integer(), server_default=sa.text("0")),
        sa.Column("docs_processed", sa.Integer(), server_default=sa.text("0")),
        sa.Column("docs_reused", sa.Integer(), server_default=sa.text("0")),
        sa.Column("docs_failed", sa.Integer(), server_default=sa.text("0")),
        sa.Column("error", sa.Text()),
        sa.Column("trace_id", sa.Text()),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.execute(
        "CREATE INDEX ix_jobs_library ON jobs (library_id, created_at DESC)"
    )

    op.create_table(
        "chunk_inventory",
        sa.Column("library_id", sa.Text(), nullable=False),
        # PK column → implicitly NOT NULL. The app uses a sentinel string for
        # unversioned libraries (see s3.py).
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("last_seen_job", sa.Text()),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("library_id", "version", "document_id"),
    )
    op.create_index(
        "ix_inventory_hash",
        "chunk_inventory",
        ["library_id", "content_hash"],
    )

    op.execute(
        "CREATE INDEX ix_libraries_name_trgm "
        "ON libraries USING GIN (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_libraries_description_trgm "
        "ON libraries USING GIN (description gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_libraries_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_libraries_name_trgm")
    op.drop_index("ix_inventory_hash", table_name="chunk_inventory")
    op.drop_table("chunk_inventory")
    op.execute("DROP INDEX IF EXISTS ix_jobs_library")
    op.drop_table("jobs")
    op.drop_table("library_versions")
    op.execute("DROP INDEX IF EXISTS ix_aliases_alias_lower")
    op.drop_table("library_aliases")
    op.drop_table("libraries")
