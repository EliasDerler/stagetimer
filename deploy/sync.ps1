<#
.SYNOPSIS
    Sync StageTimer from this Windows dev machine to the Raspberry Pi and
    restart it.

.DESCRIPTION
    Copies src/, deploy/, and pyproject.toml to /opt/stagetimer on the Pi via
    scp, then reinstalls the package into the Pi's venv and restarts the
    running kiosk process. Requires the Windows OpenSSH client (ssh/scp) and
    SSH access to the Pi.

    For repeated use, set up key-based SSH auth to avoid retyping the
    password each run:
        ssh-keygen -t ed25519
        ssh-copy-id admin@raspberrypi.local   (or manually append the
        contents of id_ed25519.pub to ~/.ssh/authorized_keys on the Pi)

.PARAMETER PiHost
    SSH host, e.g. admin@raspberrypi.local

.PARAMETER FirstTimeSetup
    Also run deploy/install.sh on the Pi after syncing (labwc/seatd install,
    venv creation, autostart configuration). Only needed once per Pi.
#>
param(
    [string]$PiHost = "admin@raspberrypi.local",
    [switch]$FirstTimeSetup
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "==> Ensuring /opt/stagetimer exists on ${PiHost}..."
ssh $PiHost "sudo mkdir -p /opt/stagetimer && sudo chown `$(whoami):`$(whoami) /opt/stagetimer"

Write-Host "==> Copying source tree to ${PiHost}:/opt/stagetimer ..."
scp -r "$ProjectRoot\src" "$ProjectRoot\deploy" "$ProjectRoot\pyproject.toml" "${PiHost}:/opt/stagetimer/"

if ($FirstTimeSetup) {
    Write-Host "==> Running first-time Pi setup (install.sh)..."
    ssh $PiHost "cd /opt/stagetimer && chmod +x deploy/install.sh deploy/labwc/autostart && sudo ./deploy/install.sh"
    Write-Host "==> First-time setup complete. Reboot the Pi to start the kiosk display: ssh $PiHost sudo reboot"
} else {
    Write-Host "==> Reinstalling package in the Pi's venv..."
    ssh $PiHost "/opt/stagetimer/venv/bin/pip install --upgrade /opt/stagetimer"

    Write-Host "==> Restarting StageTimer on the Pi..."
    ssh $PiHost "pkill -f 'python -m stagetimer' || true"
    Write-Host "    (the labwc autostart respawn loop will relaunch it within ~2s)"
}

Write-Host "==> Done."
