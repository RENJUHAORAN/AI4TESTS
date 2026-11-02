from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def work_dir() -> Iterator[Path]:
    path = (
        Path(__file__).resolve().parent
        / "discovery-work"
        / uuid.uuid4().hex
    )
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        _remove_tree(path)


def _remove_tree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink(missing_ok=True)
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
