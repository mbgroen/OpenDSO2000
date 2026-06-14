"""Colour palette and Qt style sheet that mimic the DSO2000 front panel."""

# Channel colours roughly matching the instrument's on-screen traces.
CH_COLORS = {
    1: "#f2d011",   # CH1 yellow
    2: "#13c4f0",   # CH2 cyan
}
MATH_COLOR = "#c060f0"   # purple
TRIGGER_COLOR = "#ff6a00"
GRID_COLOR = "#2a3340"
GRID_AXIS_COLOR = "#465a6e"
SCREEN_BG = "#0a0f14"

# Front-panel chrome.
PANEL_BG = "#1c1f24"
PANEL_BG_LIGHT = "#262a31"
TEXT = "#e6e9ee"
TEXT_DIM = "#9aa4b1"
ACCENT = "#3a7afe"

QSS = f"""
QMainWindow, QWidget {{
    background: {PANEL_BG};
    color: {TEXT};
    font-family: -apple-system, "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 12px;
}}
QGroupBox {{
    background: {PANEL_BG_LIGHT};
    border: 1px solid #333842;
    border-radius: 8px;
    margin-top: 14px;
    padding: 8px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT_DIM};
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 1px;
}}
QPushButton {{
    background: #2f343d;
    border: 1px solid #3c424d;
    border-radius: 6px;
    padding: 6px 10px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #393f4a; }}
QPushButton:pressed {{ background: {ACCENT}; border-color: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton:disabled {{ color: #5b626c; background: #24272d; }}
QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #14171c;
    border: 1px solid #3c424d;
    border-radius: 5px;
    padding: 4px 6px;
    color: {TEXT};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: #14171c;
    selection-background-color: {ACCENT};
    color: {TEXT};
}}
QLabel#valueLabel {{
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
    font-size: 13px;
    color: {TEXT};
}}
QLabel#statusLabel {{ color: {TEXT_DIM}; }}
QSlider::groove:vertical {{ width: 4px; background: #14171c; border-radius: 2px; }}
QSlider::handle:vertical {{
    height: 16px; margin: 0 -7px; border-radius: 8px;
    background: {ACCENT};
}}
QTabWidget::pane {{ border: 1px solid #333842; border-radius: 8px; }}
QTabBar::tab {{
    background: #24272d; padding: 6px 12px; margin: 2px;
    border-radius: 6px; color: {TEXT_DIM};
}}
QTabBar::tab:selected {{ background: {ACCENT}; color: white; }}
"""
