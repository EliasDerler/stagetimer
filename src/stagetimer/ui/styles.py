from stagetimer import config

MAIN_WINDOW_QSS = f"background-color: {config.COLOR_BACKGROUND};"

CURRENT_BOX_QSS = f"""
QFrame#currentBox {{
    border: 3px solid {config.COLOR_ACCENT_BLUE};
    background-color: rgba(59, 130, 246, 0.15);
    border-radius: 4px;
}}
QLabel#currentCaption {{
    color: {config.COLOR_NORMAL};
    font-size: 20px;
}}
QLabel#currentName {{
    color: {config.COLOR_NORMAL};
    font-size: 44px;
    font-weight: bold;
}}
QLabel#currentDescription {{
    color: {config.COLOR_NORMAL};
    font-size: 22px;
    padding-left: 12px;
}}
"""

NEXT_LABEL_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px; font-weight: bold;"
NEXT_NAME_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px;"
NEXT_DURATION_QSS = f"color: {config.COLOR_NORMAL}; font-size: 22px;"
NEXT_DESCRIPTION_QSS = f"color: {config.COLOR_NORMAL}; font-size: 18px;"

DIVIDER_QSS = f"background-color: {config.COLOR_NORMAL}; min-height: 2px; max-height: 2px;"

REALTIME_CLOCK_QSS = f"color: {config.COLOR_NORMAL}; font-size: 22px; font-weight: 600;"

MINI_TIMETABLE_QSS = f"""
QListWidget {{
    background: transparent;
    border: none;
    color: {config.COLOR_NORMAL};
    font-size: 13px;
}}
QListWidget::item {{
    padding: 1px 0;
}}
"""

SCHEDULE_DELAY_BEHIND_QSS = (
    f"color: {config.COLOR_DANGER}; background: rgba(255,59,48,0.15); "
    "font-size: 20px; font-weight: bold; padding: 4px 14px; border-radius: 14px;"
)
SCHEDULE_DELAY_ONTIME_QSS = (
    f"color: {config.COLOR_SUCCESS_GREEN}; background: rgba(34,197,94,0.15); "
    "font-size: 20px; font-weight: bold; padding: 4px 14px; border-radius: 14px;"
)
