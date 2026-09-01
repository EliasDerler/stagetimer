import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from stagetimer.ui.display_widgets import fit_clock_font_pixel_size, format_remaining


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_format_remaining_switches_to_hh_mm_ss_at_60_minutes():
    assert format_remaining(59 * 60 + 59) == "59:59"
    assert format_remaining(60 * 60) == "01:00:00"
    assert format_remaining(75 * 60) == "01:15:00"


def test_fit_clock_font_pixel_size_uses_height_candidate_when_it_fits(qapp):
    # A short "MM:SS" string in a wide widget shouldn't need shrinking below
    # the height-derived candidate.
    size = fit_clock_font_pixel_size("12:34", "Arial", True, available_width=2000, available_height=400)
    assert size == max(10, int(400 * 0.65))


def test_fit_clock_font_pixel_size_shrinks_long_text_to_fit(qapp):
    width, height = 500, 400
    height_candidate = max(10, int(height * 0.65))

    mm_ss_size = fit_clock_font_pixel_size("12:34", "Arial", True, width, height)
    hh_mm_ss_size = fit_clock_font_pixel_size("01:12:34", "Arial", True, width, height)

    # The longer HH:MM:SS string must be shrunk more than (or as much as)
    # the shorter MM:SS string for the same box — this is the bug: before
    # the fix, both used the same height-only size regardless of width.
    assert hh_mm_ss_size <= mm_ss_size
    assert hh_mm_ss_size < height_candidate

    font = QFont("Arial")
    font.setBold(True)
    font.setPixelSize(hh_mm_ss_size)
    rendered_width = QFontMetrics(font).horizontalAdvance("01:12:34")
    assert rendered_width <= width * 0.92 + 1  # small tolerance for rounding


def test_fit_clock_font_pixel_size_never_goes_below_minimum(qapp):
    size = fit_clock_font_pixel_size(
        "01:12:34", "Arial", True, available_width=5, available_height=400, min_size=10
    )
    assert size == 10


def test_fit_clock_font_pixel_size_empty_text_returns_height_candidate(qapp):
    size = fit_clock_font_pixel_size("", "Arial", True, available_width=10, available_height=400)
    assert size == max(10, int(400 * 0.65))
