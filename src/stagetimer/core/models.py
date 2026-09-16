from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import time


@dataclass
class Event:
    name: str
    start_time: time | None
    duration_seconds: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    shrinkable: bool = False
    min_duration_seconds: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time.strftime("%H:%M:%S") if self.start_time else None,
            "duration_seconds": self.duration_seconds,
            "description": self.description,
            "shrinkable": self.shrinkable,
            "min_duration_seconds": self.min_duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        raw_start = data.get("start_time")
        if raw_start:
            hh, mm, ss = (int(part) for part in raw_start.split(":"))
            start_time = time(hh, mm, ss)
        else:
            start_time = None
        return cls(
            id=data["id"],
            name=data["name"],
            start_time=start_time,
            duration_seconds=int(data["duration_seconds"]),
            description=data.get("description", ""),
            shrinkable=bool(data.get("shrinkable", False)),
            min_duration_seconds=int(data.get("min_duration_seconds", 0)),
        )


@dataclass
class Timetable:
    events: list[Event] = field(default_factory=list)
    logo_path: str | None = None
    version: int = 1

    def sorted_events(self) -> list[Event]:
        """Returns events in list order (the order they'll play in) — despite
        the name, this no longer sorts by start_time, since start_time can be
        None. List order is the source of truth for playback order; the
        config window's Move Up/Move Down buttons are how operators reorder
        it."""
        return list(self.events)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "logo_path": self.logo_path,
            "events": [e.to_dict() for e in self.sorted_events()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Timetable":
        events = [Event.from_dict(e) for e in data.get("events", [])]
        return cls(
            events=events,
            logo_path=data.get("logo_path"),
            version=data.get("version", 1),
        )
