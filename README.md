# StageTimer

A fullscreen countdown timer for live events, built for a Raspberry Pi 5 connected to an audience-facing display. Shows the current event's countdown large and centered, the next event below it, and turns yellow / red / flashing red-white as time runs low.

![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![PySide6](https://img.shields.io/badge/UI-PySide6-green)

## Features

- Fullscreen kiosk display: current event, countdown clock, next event
- Color states: white → yellow (5 min) → red (3 min) → flashing red/white (1 min)
- Optional background watermark image behind the clock
- Hybrid scheduling: events can have a fixed wall-clock start time, or chain automatically off the previous event's end — or skip start times entirely and drive the whole day manually with a **Start** button
- Live operator controls: pause/resume, skip next/prev, ±1 minute, all available both as keyboard shortcuts on the main display and as buttons in the config window
- `Ctrl+E` opens a configuration window to build the day's timetable, upload a logo, and control playback — no restart needed
- Runs unattended via systemd/labwc autostart, survives reboots and crashes

## Requirements

- Raspberry Pi 5 (or any Linux machine with a display) running Raspberry Pi OS Lite (64-bit)
- Python 3.11+
- A display connected via HDMI

Development also works cross-platform on Windows/macOS/Linux, since PySide6 is cross-platform — see [Development](#development) below.

## Installing on a Raspberry Pi

1. Flash **Raspberry Pi OS Lite (64-bit)** to an SD card and boot the Pi. Enable SSH (via `raspi-config` or the Raspberry Pi Imager's advanced options).

2. Clone this repo onto the Pi (or copy it over via `scp`/`rsync`) to `/opt/stagetimer`:

   ```bash
   sudo mkdir -p /opt/stagetimer
   sudo chown "$(whoami):$(whoami)" /opt/stagetimer
   git clone https://github.com/<your-username>/stagetimer.git /opt/stagetimer
   ```

3. Run the install script — it installs `labwc`/`seatd`, creates a Python venv, installs the app, sets the timezone, configures console autologin, and wires up the autostart chain:

   ```bash
   cd /opt/stagetimer
   chmod +x deploy/install.sh deploy/labwc/autostart
   sudo ./deploy/install.sh
   ```

   The script sets the timezone to `Europe/Vienna` — edit the `timedatectl set-timezone` line in `deploy/install.sh` first if you need a different one.

4. Reboot. StageTimer should come up fullscreen automatically:

   ```bash
   sudo reboot
   ```

If it doesn't, see [Troubleshooting](#troubleshooting) below.

### Redeploying after code changes

From a dev machine with the repo checked out, `deploy/sync.ps1` (PowerShell) copies the source tree to the Pi, reinstalls the package, and restarts the running process:

```powershell
.\deploy\sync.ps1 -PiHost admin@raspberrypi.local
```

Pass `-FirstTimeSetup` on the very first deploy to also run `install.sh` remotely instead of doing steps 2-3 above by hand.

## Using it

- **`Ctrl+E`** — open/close the configuration window
- **Space** — pause/resume the current event
- **←** / **P** — skip to previous event
- **→** / **N** — skip to next event
- **↑** / **+** — add 1 minute to the current event
- **↓** / **-** — subtract 1 minute

In the config window:
- **Add / Edit / Delete / Move Up / Move Down** — build the timetable. Each event has a name, an optional start time (uncheck "Has start time" for an event that just runs right after the previous one), and a duration.
- **Choose Logo...** — set a small logo shown top-right
- **Start** — jump straight to the first event now (only enabled when nothing is currently playing) — the way to kick off a timetable that has no fixed start times at all
- The same Pause/Resume/Skip/±1 min controls as the keyboard shortcuts

Your timetable is saved automatically on every edit to `~/.local/share/stagetimer/timetable.json`.

## Development

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"      # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # macOS/Linux

.venv\Scripts\python -m pytest tests/ -q                     # core logic tests
QT_QPA_PLATFORM=offscreen .venv/Scripts/python -m pytest tests/ -q   # + UI tests, headless

.venv\Scripts\python -m stagetimer --windowed   # run in a normal window instead of fullscreen kiosk
```

## Project layout

```
src/stagetimer/
  core/           # pure Python: scheduling, playback state, persistence — no Qt
  ui/             # PySide6 widgets: main display, config window
  assets/         # bundled images (e.g. background watermark)
deploy/
  install.sh      # Pi-side setup: packages, venv, autostart, timezone
  sync.ps1        # push code + restart from a Windows dev machine
  stagetimer.service   # optional systemd-user alternative to the labwc autostart path
  labwc/autostart      # respawn-loop launcher run by labwc on login
tests/            # pytest suite (core logic + offscreen Qt UI tests)
docs/superpowers/ # design specs and implementation plans for past features
```

## Troubleshooting

- **Blank screen / no autologin**: `systemctl status getty@tty1` — should be `active`. Check `/etc/systemd/system/getty@tty1.service.d/autologin.conf` exists.
- **labwc not starting**: check `~/.bash_profile` execs `labwc` (not `seatd-launch -- labwc` — that conflicts with the system `seatd.service`).
- **App not running**: `ps aux | grep stagetimer`. Logs from the respawn loop aren't captured anywhere by default; run `/opt/stagetimer/venv/bin/python -m stagetimer` manually over SSH (with a display attached) to see errors directly.
- **Timetable not saving / wrong location**: data lives at `~/.local/share/stagetimer/timetable.json` for whichever user the app runs as.
