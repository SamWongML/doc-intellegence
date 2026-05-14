"""GitHub source: clone a local repo, glob, yield FileRecords."""

from __future__ import annotations

import shutil
from pathlib import Path

import pygit2
import pytest
from doc_search_worker.sources.github import iter_files, parse_org_repo


@pytest.fixture
def local_git_repo(tmp_path: Path, sample_repo_dir: Path) -> Path:
    repo_path = tmp_path / "source-repo"
    shutil.copytree(sample_repo_dir, repo_path)
    repo = pygit2.init_repository(str(repo_path), bare=False)
    index = repo.index
    index.add_all()
    index.write()
    tree = index.write_tree()
    author = pygit2.Signature("Test", "test@example.com")
    repo.create_commit("HEAD", author, author, "init", tree, [])
    return repo_path


def test_parse_org_repo_variants() -> None:
    assert parse_org_repo("https://github.com/vercel/next.js") == "vercel/next.js"
    assert parse_org_repo("https://github.com/vercel/next.js.git") == "vercel/next.js"
    assert parse_org_repo("https://github.com/vercel/next.js/") == "vercel/next.js"


def test_iter_files_clones_and_globs(local_git_repo: Path) -> None:
    records = list(
        iter_files(
            url=str(local_git_repo),
            ref=None,
            doc_paths=["docs/**/*.md", "docs/**/*.mdx"],
        )
    )
    rel_paths = {r.rel_path for r in records}
    assert "docs/getting-started.md" in rel_paths
    assert "docs/app-router/routing/middleware.mdx" in rel_paths
    # source_url uses the parsed org/repo
    md_rec = next(r for r in records if r.rel_path.endswith("getting-started.md"))
    assert md_rec.source_url.endswith("source-repo/blob/HEAD/docs/getting-started.md")
    assert md_rec.data.startswith(b"# Getting Started")


def test_iter_files_respects_doc_paths_filter(local_git_repo: Path) -> None:
    # Only .md (not .mdx) → mdx file is excluded.
    records = list(iter_files(url=str(local_git_repo), ref=None, doc_paths=["docs/**/*.md"]))
    rel_paths = {r.rel_path for r in records}
    assert "docs/getting-started.md" in rel_paths
    assert "docs/app-router/routing/middleware.mdx" not in rel_paths
