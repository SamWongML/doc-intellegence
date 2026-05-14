"""GitHub source: shallow-clone via ``pygit2`` and yield matching files."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path

import pygit2

from ..logging_utils import log

_DEFAULT_GLOB: tuple[str, ...] = ("**/*.md", "**/*.mdx")

Cloner = Callable[[str, str | None], AbstractContextManager[Path]]


@dataclass(slots=True)
class FileRecord:
    rel_path: str
    data: bytes
    source_url: str


def iter_files(
    url: str,
    ref: str | None,
    doc_paths: list[str],
    *,
    cloner: Cloner | None = None,
) -> Iterator[FileRecord]:
    """Clone ``url`` at ``ref`` and yield each file matching ``doc_paths`` globs."""
    org_repo = parse_org_repo(url)
    ref_for_url = ref or "HEAD"
    do_clone = cloner or pygit2_clone
    with do_clone(url, ref) as repo_dir:
        for rel in _iter_matches(repo_dir, doc_paths or list(_DEFAULT_GLOB)):
            abs_path = repo_dir / rel
            try:
                data = abs_path.read_bytes()
            except OSError as exc:
                log.warning("github.read_error", path=str(rel), error=str(exc))
                continue
            source_url = f"https://github.com/{org_repo}/blob/{ref_for_url}/{rel.as_posix()}"
            yield FileRecord(rel_path=rel.as_posix(), data=data, source_url=source_url)


def parse_org_repo(url: str) -> str:
    """``https://github.com/org/repo[.git][/]`` → ``org/repo``."""
    stripped = url.strip().rstrip("/")
    if stripped.endswith(".git"):
        stripped = stripped[:-4]
    parts = stripped.split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return stripped


@contextmanager
def pygit2_clone(url: str, ref: str | None) -> Iterator[Path]:
    """Clone ``url`` at ``ref`` into a temp dir; yield the clone path."""
    with tempfile.TemporaryDirectory(prefix="doc-search-clone-") as tmp:
        dest = Path(tmp) / "repo"
        log.info("github.clone", url=url, ref=ref, dest=str(dest))
        if ref:
            pygit2.clone_repository(url, str(dest), checkout_branch=ref)
        else:
            pygit2.clone_repository(url, str(dest))
        yield dest


def _iter_matches(root: Path, patterns: list[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for pat in patterns:
        for match in sorted(root.glob(pat)):
            if not match.is_file():
                continue
            rel = match.relative_to(root)
            if rel in seen:
                continue
            seen.add(rel)
            yield rel


__all__ = ["Cloner", "FileRecord", "iter_files", "parse_org_repo", "pygit2_clone"]
