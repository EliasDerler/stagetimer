from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import time


@dataclass
class Event:
    name: str
    start_time: time
    duration_seconds: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def end_time_seconds(self) -> int:
        """Seconds-since-midnight at which this event ends."""
        start_seconds = self.start_time.hour * 3600 + self.start_time.minute * 60 + self.start_time.second
        return start_seconds + self.duration_seconds

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time.strftime("%H:%M:%S"),
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        hh, mm, ss = (int(part) for part in data["start_time"].split(":"))
        return cls(
            id=data["id"],
            name=data["name"],
            start_time=time(hh, mm, ss),
            duration_seconds=int(data["duration_seconds"]),
        )


@dataclass
class Timetable:
    events: list[Event] = field(default_factory=list)
    logo_path: str | None = None
    version: int = 1

    def sorted_events(self) -> list[Event]:
        return sorted(self.events, key=lambda e: e.start_time)

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
