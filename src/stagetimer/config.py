from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TIMETABLE_PATH = DATA_DIR / "timetable.json"
LOGO_PATH = DATA_DIR / "logo.png"

# Colors
COLOR_NORMAL = "#FFFFFF"
COLOR_WARNING = "#FFD300"
COLOR_DANGER = "#FF3B30"
COLOR_FLASH_ALT = "#FFFFFF"
COLOR_BACKGROUND = "#000000"

# Timing
TICK_INTERVAL_MS = 200
FLASH_INTERVAL_MS = 500
