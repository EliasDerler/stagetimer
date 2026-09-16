from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from stagetimer.core import persistence
from stagetimer.core.models import Timetable

DAY_NAME_FALLBACK = "Day 1"


@dataclass
class DayMeta:
    id: str
    name: str
    modified_at: float


def _day_path(days_dir: Path, day_id: str) -> Path:
    return days_dir / f"{day_id}.json"


def _backup_corrupt_file(path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{timestamp}")
    try:
        path.replace(backup_path)
        print(f"stagetimer: backed up corrupt day file to {backup_path}", file=sys.stderr)
    except OSError as exc:
        print(f"stagetimer: failed to back up corrupt day file {path}: {exc}", file=sys.stderr)


def list_days(days_dir: Path) -> list[DayMeta]:
    if not days_dir.exists():
        return []
    metas: list[DayMeta] = []
    for path in days_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            metas.append(DayMeta(id=data["id"], name=data["name"], modified_at=path.stat().st_mtime))
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as exc:
            print(f"stagetimer: failed to read day file {path}: {exc}", file=sys.stderr)
            _backup_corrupt_file(path)
    return sorted(metas, key=lambda m: m.name)


def load_day(days_dir: Path, day_id: str) -> Timetable:
    path = _day_path(days_dir, day_id)
    if not path.exists():
        return Timetable()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Timetable.from_dict(data["timetable"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        print(f"stagetimer: failed to load day {path}: {exc}", file=sys.stderr)
        _backup_corrupt_file(path)
        return Timetable()


def save_day(days_dir: Path, day_id: str, name: str, timetable: Timetable) -> None:
    days_dir.mkdir(parents=True, exist_ok=True)
    path = _day_path(days_dir, day_id)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = {"id": day_id, "name": name, "timetable": timetable.to_dict()}
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


def create_day(days_dir: Path, name: str, timetable: Timetable | None = None) -> str:
    day_id = str(uuid.uuid4())
    save_day(days_dir, day_id, name, timetable if timetable is not None else Timetable())
    return day_id


def rename_day(days_dir: Path, day_id: str, new_name: str) -> None:
    timetable = load_day(days_dir, day_id)
    save_day(days_dir, day_id, new_name, timetable)


def delete_day(days_dir: Path, day_id: str) -> None:
    path = _day_path(days_dir, day_id)
    if path.exists():
        path.unlink()


def get_active_day_id(active_day_path: Path) -> str | None:
    if not active_day_path.exists():
        return None
    try:
        data = json.loads(active_day_path.read_text(encoding="utf-8"))
        return data.get("active_day_id")
    except (json.JSONDecodeError, OSError):
        return None


def set_active_day_id(active_day_path: Path, day_id: str) -> None:
    active_day_path.parent.mkdir(parents=True, exist_ok=True)
    active_day_path.write_text(json.dumps({"active_day_id": day_id}), encoding="utf-8")


def clear_active_day(active_day_path: Path) -> None:
    if active_day_path.exists():
        active_day_path.unlink()


def ensure_startup_day(days_dir: Path, active_day_path: Path, legacy_timetable_path: Path) -> str:
    days = list_days(days_dir)
    if days:
        active_id = get_active_day_id(active_day_path)
        if active_id and any(d.id == active_id for d in days):
            return active_id
        fallback_id = days[0].id
        set_active_day_id(active_day_path, fallback_id)
        return fallback_id

    if legacy_timetable_path.exists():
        legacy_timetable = persistence.load(legacy_timetable_path)
        day_id = create_day(days_dir, DAY_NAME_FALLBACK, legacy_timetable)
        set_active_day_id(active_day_path, day_id)
        return day_id

    day_id = create_day(days_dir, DAY_NAME_FALLBACK, Timetable())
    set_active_day_id(active_day_path, day_id)
    return day_id
