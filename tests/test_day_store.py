import json
from pathlib import Path

import pytest

from stagetimer.core import day_store
from stagetimer.core.models import Event, Timetable


@pytest.fixture
def days_dir(tmp_path: Path) -> Path:
    return tmp_path / "days"


@pytest.fixture
def active_day_path(tmp_path: Path) -> Path:
    return tmp_path / "active_day.json"


def test_create_then_load_day_roundtrip(days_dir):
    timetable = Timetable(events=[Event(name="Keynote", start_time=None, duration_seconds=600)])
    day_id = day_store.create_day(days_dir, "Friday", timetable)

    loaded = day_store.load_day(days_dir, day_id)

    assert [e.name for e in loaded.events] == ["Keynote"]


def test_create_day_defaults_to_empty_timetable(days_dir):
    day_id = day_store.create_day(days_dir, "Friday")

    loaded = day_store.load_day(days_dir, day_id)

    assert loaded.events == []


def test_list_days_returns_names_sorted(days_dir):
    day_store.create_day(days_dir, "Saturday")
    day_store.create_day(days_dir, "Friday")

    names = [d.name for d in day_store.list_days(days_dir)]

    assert names == ["Friday", "Saturday"]


def test_list_days_on_missing_directory_returns_empty(days_dir):
    assert day_store.list_days(days_dir) == []


def test_save_day_overwrites_existing_day(days_dir):
    day_id = day_store.create_day(days_dir, "Friday", Timetable(events=[Event(name="A", start_time=None, duration_seconds=60)]))

    day_store.save_day(days_dir, day_id, "Friday", Timetable(events=[Event(name="B", start_time=None, duration_seconds=60)]))

    loaded = day_store.load_day(days_dir, day_id)
    assert [e.name for e in loaded.events] == ["B"]
    assert len(day_store.list_days(days_dir)) == 1


def test_rename_day_keeps_id_and_events_changes_name(days_dir):
    day_id = day_store.create_day(days_dir, "Friday", Timetable(events=[Event(name="A", start_time=None, duration_seconds=60)]))

    day_store.rename_day(days_dir, day_id, "Opening Night")

    days = day_store.list_days(days_dir)
    assert len(days) == 1
    assert days[0].id == day_id
    assert days[0].name == "Opening Night"
    assert [e.name for e in day_store.load_day(days_dir, day_id).events] == ["A"]


def test_delete_day_removes_it(days_dir):
    day_id = day_store.create_day(days_dir, "Friday")
    other_id = day_store.create_day(days_dir, "Saturday")

    day_store.delete_day(days_dir, day_id)

    assert [d.id for d in day_store.list_days(days_dir)] == [other_id]


def test_delete_nonexistent_day_is_noop(days_dir):
    day_store.delete_day(days_dir, "does-not-exist")
    assert day_store.list_days(days_dir) == []


def test_load_day_missing_file_returns_empty_timetable(days_dir):
    result = day_store.load_day(days_dir, "does-not-exist")
    assert result.events == []


def test_load_day_corrupt_file_backs_up_and_returns_empty(days_dir):
    days_dir.mkdir(parents=True)
    bad_path = days_dir / "bad-id.json"
    bad_path.write_text("{not valid json", encoding="utf-8")

    result = day_store.load_day(days_dir, "bad-id")

    assert result.events == []
    backups = list(days_dir.glob("bad-id.json.bak-*"))
    assert len(backups) == 1
    assert not bad_path.exists()


def test_list_days_skips_and_backs_up_corrupt_file(days_dir):
    days_dir.mkdir(parents=True)
    (days_dir / "bad-id.json").write_text("{not valid json", encoding="utf-8")
    day_store.create_day(days_dir, "Friday")

    days = day_store.list_days(days_dir)

    assert [d.name for d in days] == ["Friday"]
    assert list(days_dir.glob("bad-id.json.bak-*"))


def test_active_day_roundtrip(active_day_path):
    assert day_store.get_active_day_id(active_day_path) is None

    day_store.set_active_day_id(active_day_path, "abc-123")
    assert day_store.get_active_day_id(active_day_path) == "abc-123"


def test_clear_active_day_removes_pointer(active_day_path):
    day_store.set_active_day_id(active_day_path, "abc-123")
    day_store.clear_active_day(active_day_path)
    assert day_store.get_active_day_id(active_day_path) is None


def test_clear_active_day_when_nothing_set_is_noop(active_day_path):
    day_store.clear_active_day(active_day_path)
    assert day_store.get_active_day_id(active_day_path) is None


def test_ensure_startup_day_uses_valid_active_pointer(days_dir, active_day_path, tmp_path):
    day_a = day_store.create_day(days_dir, "Friday")
    day_store.create_day(days_dir, "Saturday")
    day_store.set_active_day_id(active_day_path, day_a)

    result = day_store.ensure_startup_day(days_dir, active_day_path, tmp_path / "legacy.json")

    assert result == day_a


def test_ensure_startup_day_falls_back_when_active_pointer_is_stale(days_dir, active_day_path, tmp_path):
    day_store.create_day(days_dir, "Friday")
    day_store.set_active_day_id(active_day_path, "some-id-that-was-deleted")

    result = day_store.ensure_startup_day(days_dir, active_day_path, tmp_path / "legacy.json")

    assert result in [d.id for d in day_store.list_days(days_dir)]
    assert day_store.get_active_day_id(active_day_path) == result


def test_ensure_startup_day_migrates_legacy_timetable(days_dir, active_day_path, tmp_path):
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "logo_path": None,
                "events": [{"id": "x", "name": "Legacy Event", "start_time": None, "duration_seconds": 60}],
            }
        ),
        encoding="utf-8",
    )

    result = day_store.ensure_startup_day(days_dir, active_day_path, legacy_path)

    days = day_store.list_days(days_dir)
    assert len(days) == 1
    assert days[0].name == "Day 1"
    assert [e.name for e in day_store.load_day(days_dir, result).events] == ["Legacy Event"]
    assert legacy_path.exists()  # left untouched, not deleted
    assert day_store.get_active_day_id(active_day_path) == result


def test_ensure_startup_day_creates_empty_day_1_when_nothing_exists(days_dir, active_day_path, tmp_path):
    result = day_store.ensure_startup_day(days_dir, active_day_path, tmp_path / "legacy.json")

    days = day_store.list_days(days_dir)
    assert len(days) == 1
    assert days[0].name == "Day 1"
    assert day_store.load_day(days_dir, result).events == []
