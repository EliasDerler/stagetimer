from __future__ import annotations

from pathlib import Path

# Package-relative — resolves correctly both for an editable/source checkout
# and for a normal `pip install` copy (e.g. into site-packages on the Pi),
# since assets/ is bundled inside the stagetimer package itself either way.
PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
WATERMARK_PATH = ASSETS_DIR / "watermark.png"

# Bundled fonts — used instead of relying on system font availability so
# rendering (in particular digit shapes like "0") is identical and
# predictable on both this dev machine and the Pi, which doesn't have
# Consolas or any other specific font pre-installed. JetBrains Mono ships
# with a distinctive slashed zero, which is why it was chosen. Loaded via
# QFontDatabase.addApplicationFont() in app.py; FONT_FAMILY is the family
# name it registers under.
FONTS_DIR = ASSETS_DIR / "fonts"
FONT_PATHS = [FONTS_DIR / "JetBrainsMono-Regular.ttf", FONTS_DIR / "JetBrainsMono-Bold.ttf"]
FONT_FAMILY = "JetBrains Mono"

# User data directory — deliberately NOT derived from the package's install
# location (that would move to a nonsense path like .../venv/lib/pythonX.Y/
# whenever the package is reinstalled non-editable, as it was before this
# fix). A fixed per-user directory survives reinstalls/upgrades.
DATA_DIR = Path.home() / ".local" / "share" / "stagetimer"
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

# Background watermark
WATERMARK_SIDE_MARGIN_CM = 1.0
