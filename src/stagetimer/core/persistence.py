from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from stagetimer.core.models import Timetable


def load(path: Path) -> Timetable:
    """Load a Timetable from disk. Returns an empty Timetable if the file is
    missing or malformed, backing up any malformed file before returning."""
    if not path.exists():
        return Timetable()

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return Timetable.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        print(f"stagetimer: failed to load {path}: {exc}", file=sys.stderr)
        _backup_corrupt_file(path)
        return Timetable()


def save(path: Path, timetable: Timetable) -> None:
    """Atomically write the timetable to disk (write to a temp file, then
    os.replace) so a power loss mid-write can't corrupt the existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(timetable.to_dict(), indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def _backup_corrupt_file(path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
    try:
        path.replace(backup_path)
        print(f"stagetimer: backed up corrupt file to {backup_path}", file=sys.stderr)
    except OSError as exc:
        print(f"stagetimer: failed to back up corrupt file {path}: {exc}", file=sys.stderr)
