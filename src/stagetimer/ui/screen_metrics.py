from __future__ import annotations

from PySide6.QtWidgets import QWidget

# Fallback assumes a 24" 16:9 display at 1920x1080 (~531mm wide), used only
# when the connected screen doesn't report a physical size via EDID.
_FALLBACK_PX_PER_MM = 1920 / 531


def compute_margin_px(widget: QWidget, margin_cm: float) -> int:
    """Convert a margin in centimeters to pixels, using the real physical
    size (in mm) of the screen `widget` is currently shown on, so the margin
    is accurate regardless of the actual connected display."""
    screen = widget.screen()
    px_per_mm = _FALLBACK_PX_PER_MM
    if screen is not None:
        physical_width_mm = screen.physicalSize().width()
        if physical_width_mm > 0:
            px_per_mm = screen.geometry().width() / physical_width_mm
    return int(margin_cm * 10 * px_per_mm)
