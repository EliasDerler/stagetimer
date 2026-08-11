from __future__ import annotations

import argparse
import os
import sys

from stagetimer.app import run


def main() -> None:
    parser = argparse.ArgumentParser(description="StageTimer — fullscreen event countdown timer")
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Run in a normal resizable window instead of fullscreen kiosk mode (for development)",
    )
    args = parser.parse_args()

    kiosk = not args.windowed
    if os.environ.get("STAGETIMER_KIOSK") == "0":
        kiosk = False

    sys.exit(run(kiosk=kiosk))


if __name__ == "__main__":
    main()
