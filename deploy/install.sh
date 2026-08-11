#!/usr/bin/env bash
# Pi-side setup for StageTimer on Raspberry Pi OS Lite (64-bit).
# Run once on the Pi after code has been synced via deploy/sync.ps1:
#   ssh pi@host "cd /opt/stagetimer && sudo ./deploy/install.sh"
set -euo pipefail

APP_DIR="/opt/stagetimer"
APP_USER="${SUDO_USER:-$(whoami)}"

echo "==> Installing system packages (labwc, seatd, python3-venv)..."
apt-get update
apt-get install -y labwc seatd python3-venv python3-pip

echo "==> Ensuring ${APP_USER} is in the seatd access group..."
# seatd is started as `seatd -g <group>` — the actual group name varies by
# image (has been "seat" on some, "video" on current Pi OS trixie images).
# Read it from the running service instead of hardcoding one.
SEATD_GROUP=$(systemctl show -p ExecStart seatd.service 2>/dev/null | grep -oP '(?<=-g )\S+' || true)
SEATD_GROUP="${SEATD_GROUP:-video}"
if getent group "${SEATD_GROUP}" > /dev/null; then
    usermod -aG "${SEATD_GROUP}" "${APP_USER}"
else
    echo "    WARNING: seatd group '${SEATD_GROUP}' not found — skipping (seatd may use a different access model on this image)."
fi

echo "==> Creating Python virtual environment..."
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install "${APP_DIR}"

echo "==> Installing labwc autostart hook..."
mkdir -p "/home/${APP_USER}/.config/labwc"
cp "${APP_DIR}/deploy/labwc/autostart" "/home/${APP_USER}/.config/labwc/autostart"
chown -R "${APP_USER}:${APP_USER}" "/home/${APP_USER}/.config/labwc"
chmod +x "/home/${APP_USER}/.config/labwc/autostart"

echo "==> Enabling console autologin for ${APP_USER} on tty1..."
raspi-config nonint do_boot_behaviour B2

PROFILE_SNIPPET="/home/${APP_USER}/.bash_profile"
if ! grep -q "seatd-launch -- labwc" "${PROFILE_SNIPPET}" 2>/dev/null; then
    cat >> "${PROFILE_SNIPPET}" <<'EOF'

# Launch StageTimer's Wayland kiosk session on the console tty (tty1 only,
# and only if no graphical session is already running). labwc talks to the
# system seatd.service (installed/enabled as a package default) directly via
# libseat, so it's launched plain here rather than via seatd-launch — running
# seatd-launch as well would try to start a second, conflicting seatd.
if [ -z "${WAYLAND_DISPLAY}" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec labwc
fi
EOF
fi
chown "${APP_USER}:${APP_USER}" "${PROFILE_SNIPPET}"

echo "==> Done. Reboot the Pi to launch the kiosk display automatically:"
echo "      sudo reboot"
echo ""
echo "    This installs the autologin + labwc + StageTimer autostart path (see"
echo "    deploy/labwc/autostart). deploy/stagetimer.service is provided as an"
echo "    alternative systemd-managed launch path for setups that already have"
echo "    a working systemd --user / lingering session configured; it is NOT"
echo "    installed by this script since Pi OS's Wayland-session bootstrap"
echo "    mechanics can vary by image version — verify on your actual hardware."
