from datetime import time
from pathlib import Path

from stagetimer.core import persistence
from stagetimer.core.models import Event, Timetable


def test_load_missing_file_returns_empty_timetable(tmp_path: Path):
    result = persistence.load(tmp_path / "does_not_exist.json")
    assert result.events == []
    assert result.logo_path is None


def test_save_then_load_roundtrip(tmp_path: Path):
    path = tmp_path / "timetable.json"
    original = Timetable(
        events=[
            Event(name="Keynote", start_time=time(9, 0, 0), duration_seconds=1800),
            Event(name="Break", start_time=time(9, 30, 0), duration_seconds=900),
        ],
        logo_path="logo.png",
    )

    persistence.save(path, original)
    loaded = persistence.load(path)

    assert loaded.logo_path == "logo.png"
    assert [e.name for e in loaded.events] == ["Keynote", "Break"]
    assert loaded.events[0].start_time == time(9, 0, 0)
    assert loaded.events[0].duration_seconds == 1800
    assert loaded.events[0].id == original.events[0].id


def test_save_sorts_events_by_start_time(tmp_path: Path):
    path = tmp_path / "timetable.json"
    unsorted = Timetable(
        events=[
            Event(name="Second", start_time=time(10, 0, 0), duration_seconds=600),
            Event(name="First", start_time=time(9, 0, 0), duration_seconds=600),
        ]
    )

    persistence.save(path, unsorted)
    loaded = persistence.load(path)

    assert [e.name for e in loaded.events] == ["First", "Second"]


def test_load_malformed_json_backs_up_and_returns_empty(tmp_path: Path):
    path = tmp_path / "timetable.json"
    path.write_text("{not valid json", encoding="utf-8")

    result = persistence.load(path)

    assert result.events == []
    backups = list(tmp_path.glob("timetable.json.bak-*"))
    assert len(backups) == 1
    assert not path.exists()


def test_save_is_atomic_no_leftover_tmp_file(tmp_path: Path):
    path = tmp_path / "timetable.json"
    persistence.save(path, Timetable())

    assert path.exists()
    assert not (tmp_path / "timetable.json.tmp").exists()
