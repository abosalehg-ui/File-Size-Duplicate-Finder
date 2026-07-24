"""أنماط QSS وألوان المجموعات — معزولة عن منطق الواجهة."""

from __future__ import annotations

# ألوان خلفيات المجموعات — طقم فاتح وطقم داكن، مع لون نص صريح لكل طقم
# حتى لا تظهر خلفية فاتحة بنص فاتح في الوضع الداكن (أو العكس).
GROUP_COLORS_LIGHT = [
    "#E3F2FD", "#E8F5E9", "#FFF3E0", "#F3E5F5", "#E0F7FA",
    "#FBE9E7", "#F1F8E9", "#EDE7F6", "#E1F5FE", "#FFF8E1",
    "#E8EAF6", "#FCE4EC", "#E0F2F1", "#EFEBE9", "#ECEFF1",
]
GROUP_TEXT_LIGHT = "#1a1a2e"

GROUP_COLORS_DARK = [
    "#263850", "#26402b", "#4a3826", "#3d2b47", "#1f4247",
    "#47302a", "#33421f", "#322b4a", "#1f3d52", "#474021",
    "#2b3050", "#4a2635", "#1f423d", "#3d332e", "#2e3940",
]
GROUP_TEXT_DARK = "#e8eaf6"

LIGHT_QSS = """
QMainWindow { background-color: #f5f6fa; }
QGroupBox {
    font-weight: bold; font-size: 13px;
    border: 2px solid #3498db; border-radius: 8px;
    margin-top: 10px; padding-top: 10px; background-color: white;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top right;
    padding: 5px 15px; background-color: #3498db;
    color: white; border-radius: 5px;
}
QPushButton {
    background-color: #3498db; color: white; border: none;
    padding: 10px 20px; border-radius: 5px;
    font-weight: bold; font-size: 12px;
}
QPushButton:hover { background-color: #2980b9; }
QPushButton:pressed { background-color: #1c5980; }
QPushButton:disabled { background-color: #bdc3c7; }
QLineEdit, QDoubleSpinBox, QComboBox {
    padding: 8px; border: 2px solid #ddd; border-radius: 5px;
    background-color: white; font-size: 12px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #3498db; }
QTreeWidget {
    border: 2px solid #ddd; border-radius: 5px;
    background-color: white; font-size: 12px;
    alternate-background-color: #f8f9fa;
}
QTreeWidget::item { padding: 5px; border-bottom: 1px solid #eee; }
QTreeWidget::item:selected { background-color: #3498db; color: white; }
QHeaderView::section {
    background-color: #3498db; color: white;
    padding: 8px; border: none; font-weight: bold;
}
QProgressBar {
    border: 2px solid #ddd; border-radius: 5px; text-align: center;
    font-weight: bold; background-color: #ecf0f1;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #27ae60, stop:1 #2ecc71);
    border-radius: 3px;
}
QCheckBox { font-size: 12px; spacing: 8px; }
QTextEdit { border: 2px solid #ddd; border-radius: 5px; background-color: #fafafa; }
QTabWidget::pane { border: 2px solid #3498db; border-radius: 5px; background: white; }
QTabBar::tab {
    background: #ecf0f1; padding: 10px 20px; margin-right: 2px;
    border-top-left-radius: 5px; border-top-right-radius: 5px;
}
QTabBar::tab:selected { background: #3498db; color: white; }
QLabel#statsBox {
    background-color: #e8f4fc; color: #2c3e50;
    padding: 10px; border-radius: 5px; font-weight: bold;
}
QLabel#dryRunSummary {
    background-color: #E3F2FD; color: #0d2137;
    border-radius: 8px; border: 1px solid #90CAF9;
}
QLabel#warningBox {
    color: #BF360C; background-color: #FFF3E0;
    padding: 8px; border-radius: 6px; border: 1px solid #FFAB91;
}
"""

DARK_QSS = """
QMainWindow, QDialog { background-color: #1e1e2e; color: #cdd6f4; }
QWidget { color: #cdd6f4; }
QGroupBox {
    font-weight: bold; font-size: 13px;
    border: 2px solid #5c6bc0; border-radius: 8px;
    margin-top: 10px; padding-top: 10px; background-color: #2a2a3e;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top right;
    padding: 5px 15px; background-color: #5c6bc0;
    color: white; border-radius: 5px;
}
QPushButton {
    background-color: #5c6bc0; color: white; border: none;
    padding: 10px 20px; border-radius: 5px;
    font-weight: bold; font-size: 12px;
}
QPushButton:hover { background-color: #7986cb; }
QPushButton:pressed { background-color: #3949ab; }
QPushButton:disabled { background-color: #4a4a5e; color: #8a8a9e; }
QLineEdit, QDoubleSpinBox, QComboBox {
    padding: 8px; border: 2px solid #44475a; border-radius: 5px;
    background-color: #2a2a3e; color: #cdd6f4; font-size: 12px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #5c6bc0; }
QTreeWidget {
    border: 2px solid #44475a; border-radius: 5px;
    background-color: #2a2a3e; color: #cdd6f4; font-size: 12px;
    alternate-background-color: #313244;
}
QTreeWidget::item { padding: 5px; border-bottom: 1px solid #44475a; }
QTreeWidget::item:selected { background-color: #5c6bc0; color: white; }
QHeaderView::section {
    background-color: #5c6bc0; color: white;
    padding: 8px; border: none; font-weight: bold;
}
QProgressBar {
    border: 2px solid #44475a; border-radius: 5px; text-align: center;
    font-weight: bold; background-color: #313244; color: #cdd6f4;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #66bb6a, stop:1 #43a047);
    border-radius: 3px;
}
QCheckBox { font-size: 12px; spacing: 8px; color: #cdd6f4; }
QTextEdit {
    border: 2px solid #44475a; border-radius: 5px;
    background-color: #1e1e2e; color: #cdd6f4;
}
QTabWidget::pane { border: 2px solid #44475a; background-color: #2a2a3e; }
QTabBar::tab {
    background: #313244; color: #cdd6f4;
    padding: 8px 16px; border-radius: 4px;
}
QTabBar::tab:selected { background: #5c6bc0; color: white; }
QLabel { color: #cdd6f4; }
QMenu { background-color: #2a2a3e; color: #cdd6f4; border: 1px solid #44475a; }
QMenu::item:selected { background-color: #5c6bc0; }
QLabel#statsBox {
    background-color: #26344a; color: #dbe4ff;
    padding: 10px; border-radius: 5px; font-weight: bold;
}
QLabel#dryRunSummary {
    background-color: #26344a; color: #dbe4ff;
    border-radius: 8px; border: 1px solid #3d5170;
}
QLabel#warningBox {
    color: #ffccbc; background-color: #3a2a20;
    padding: 8px; border-radius: 6px; border: 1px solid #6d4030;
}
"""


def group_palette(dark_mode: bool) -> tuple[list[str], str]:
    """(قائمة ألوان الخلفيات، لون النص) حسب الوضع الحالي."""
    if dark_mode:
        return GROUP_COLORS_DARK, GROUP_TEXT_DARK
    return GROUP_COLORS_LIGHT, GROUP_TEXT_LIGHT
