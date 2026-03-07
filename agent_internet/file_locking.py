from __future__ import annotations

import copy
import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TypeVar

_T = TypeVar("_T")


def _atomic_write_json(path: Path, payload: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(path)


@contextmanager
def locked_file(path: Path, *, exclusive: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_locked_json_value(path: Path, *, default: _T) -> _T:
    with locked_file(path, exclusive=False):
        if not path.exists():
            return copy.deepcopy(default)
        return json.loads(path.read_text())


def write_locked_json_value(path: Path, payload: object) -> None:
    with locked_file(path, exclusive=True):
        _atomic_write_json(path, payload)


def update_locked_json_value(path: Path, *, default: _T, updater: Callable[[_T], _T]) -> _T:
    with locked_file(path, exclusive=True):
        current = json.loads(path.read_text()) if path.exists() else copy.deepcopy(default)
        updated = updater(current)
        _atomic_write_json(path, updated)
        return updated