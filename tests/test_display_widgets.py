import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication

from stagetimer import config
from stagetimer.core.state_machine import ScheduleRow
from stagetimer.ui.display_widgets import (
    MiniTimetable,
    fit_clock_font_pixel_size,
    format_clock_time,
    format_remaining,
)


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


def test_format_clock_time_none_is_dashes():
    assert format_clock_time(None) == "--:--"


def test_format_clock_time_formats_hh_mm():
    assert format_clock_time(9 * 3600 + 5 * 60) == "09:05"


def test_mini_timetable_set_rows_populates_list(qapp):
    rows = [
        ScheduleRow(name="Keynote", duration_seconds=1800, effective_start_seconds=9 * 3600, is_current=True),
        ScheduleRow(name="Panel", duration_seconds=1200, effective_start_seconds=None, is_current=False),
    ]
    widget = MiniTimetable()
    widget.set_rows(rows)
    assert widget.count() == 2
    assert "Keynote" in widget.item(0).text()
    assert "09:00" in widget.item(0).text()
    assert "--:--" in widget.item(1).text()


def test_mini_timetable_current_row_is_bold_and_green(qapp):
    rows = [ScheduleRow(name="Keynote", duration_seconds=1800, effective_start_seconds=9 * 3600, is_current=True)]
    widget = MiniTimetable()
    widget.set_rows(rows)
    item = widget.item(0)
    assert item.font().bold() is True
    assert item.foreground().color().name().lower() == config.COLOR_SUCCESS_GREEN.lower()


def test_mini_timetable_clears_previous_rows(qapp):
    widget = MiniTimetable()
    widget.set_rows([ScheduleRow(name="A", duration_seconds=60, effective_start_seconds=0, is_current=False)])
    widget.set_rows([ScheduleRow(name="B", duration_seconds=60, effective_start_seconds=0, is_current=False)])
    assert widget.count() == 1
    assert "B" in widget.item(0).text()


def test_mini_timetable_skips_rebuild_when_rows_unchanged(qapp, monkeypatch):
    rows = [ScheduleRow(name="Keynote", duration_seconds=1800, effective_start_seconds=9 * 3600, is_current=True)]
    widget = MiniTimetable()
    widget.set_rows(rows)

    clear_calls = []
    monkeypatch.setattr(widget, "clear", lambda: clear_calls.append(1))

    widget.set_rows(list(rows))  # same content, different list object
    assert clear_calls == []
    assert widget.count() == 1  # untouched — the skipped call never cleared it


def test_mini_timetable_rebuilds_when_rows_actually_differ(qapp, monkeypatch):
    widget = MiniTimetable()
    widget.set_rows([ScheduleRow(name="A", duration_seconds=60, effective_start_seconds=0, is_current=False)])

    clear_calls = []
    real_clear = widget.clear
    monkeypatch.setattr(widget, "clear", lambda: (clear_calls.append(1), real_clear()))

    widget.set_rows([ScheduleRow(name="B", duration_seconds=60, effective_start_seconds=0, is_current=False)])
    assert clear_calls == [1]


def test_current_box_shows_description_next_to_name(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box.set_name("Keynote")
    box.set_description("Opening remarks")
    assert box._description.text() == "Opening remarks"


def test_current_box_elides_long_description(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box._description.setFixedWidth(80)
    box.set_name("Keynote")
    long_text = "This is a very long description that will not fit in the available space at all"
    box.set_description(long_text)
    assert box._description.text() != long_text
    assert box._description.text().endswith("…")


def test_current_box_clears_description(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box.set_name("Keynote")
    box.set_description("Some notes")
    box.set_description(None)
    assert box._description.text() == ""


def test_current_box_collapses_newlines_in_description(qapp):
    from stagetimer.ui.display_widgets import CurrentBox

    box = CurrentBox()
    box.set_description("Line one\nLine two")
    assert "\n" not in box._description.text()


def test_next_bar_shows_description_when_present(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    bar.show()
    bar.set_next("Panel", 1200, "Bring extra mics")
    assert bar._description.text() == "Bring extra mics"
    assert bar._description.isVisible() is True


def test_next_bar_hides_description_row_when_absent(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    bar.show()
    bar.set_next("Panel", 1200, None)
    assert bar._description.isVisible() is False


def test_next_bar_description_word_wraps_not_truncated(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    long_text = "This is a fairly long description with several words that should wrap across multiple lines"
    bar.set_next("Panel", 1200, long_text)
    assert bar._description.text() == long_text
    assert bar._description.wordWrap() is True


def test_next_bar_hides_entirely_when_no_next_event(qapp):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    bar.show()
    bar.set_next("Panel", 1200, "notes")
    bar.set_next(None, None)
    assert bar.isVisible() is False


def test_next_bar_skips_redundant_update_when_args_unchanged(qapp, monkeypatch):
    from stagetimer.ui.display_widgets import NextBar

    bar = NextBar()
    bar.show()
    bar.set_next("Panel", 1200, "notes")

    set_text_calls = []
    monkeypatch.setattr(bar._name, "setText", lambda text: set_text_calls.append(text))

    bar.set_next("Panel", 1200, "notes")  # identical args — should be skipped by the guard
    assert set_text_calls == []
