from stagetimer import config

MAIN_WINDOW_QSS = f"background-color: {config.COLOR_BACKGROUND};"

CURRENT_BOX_QSS = f"""
QFrame#currentBox {{
    border: 3px solid {config.COLOR_NORMAL};
    border-radius: 4px;
}}
QLabel#currentCaption {{
    color: {config.COLOR_NORMAL};
    font-size: 20px;
}}
QLabel#currentName {{
    color: {config.COLOR_NORMAL};
    font-size: 28px;
    font-weight: bold;
}}
"""

NEXT_LABEL_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px; font-weight: bold;"
NEXT_NAME_QSS = f"color: {config.COLOR_NORMAL}; font-size: 26px;"
NEXT_DURATION_QSS = f"color: {config.COLOR_NORMAL}; font-size: 22px;"

DIVIDER_QSS = f"background-color: {config.COLOR_NORMAL}; min-height: 2px; max-height: 2px;"
