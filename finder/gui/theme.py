"""نظام التصميم: رموز الألوان والمقاسات، وبناء QSS و QPalette منها.

المبدأ: لا لون مكتوب يدوياً داخل منطق الواجهة. كل شيء يأتي من ``Palette``
واحدة لكل وضع (فاتح/داكن)، فيبقى الوضعان متسقين ويستحيل أن يظهر نص فاتح
على خلفية فاتحة.

- ``palette(dark)`` — رموز الألوان الحالية (للاستخدام في الأكواد أيضاً).
- ``stylesheet(dark)`` — QSS كامل مبني من الرموز.
- ``qt_palette(dark)`` — ``QPalette`` حتى تتبع العناصر التي يرسمها Qt نفسه
  (مؤشرات الاختيار، الأسهم، أشرطة التمرير، الحوارات القياسية) نفس الثيم.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtGui import QColor, QPalette

from . import icons

# خط عربي/لاتيني مقروء مع بدائل لكل منصّة
FONT_STACK = (
    '"Segoe UI", "Noto Sans Arabic", "Dubai", "Tahoma", '
    '"Noto Sans", "DejaVu Sans", sans-serif'
)
MONO_STACK = '"Cascadia Mono", "Consolas", "Noto Sans Mono", "DejaVu Sans Mono", monospace'

# مقاس الشبكة — كل الهوامش والمسافات مضاعفات هذه القيم
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG = 4, 8, 12, 16
RADIUS_XS, RADIUS_SM, RADIUS_MD, RADIUS_LG = 4, 6, 8, 12
ICON_SM, ICON_MD, ICON_LG = 15, 17, 20


@dataclass(frozen=True)
class Palette:
    """رموز ألوان وضع واحد."""

    dark: bool
    bg: str            # خلفية النافذة
    surface: str       # خلفية البطاقات والحقول
    surface_alt: str   # صفوف متبادلة، رؤوس الأعمدة
    surface_sunken: str  # مناطق غائرة (مسار التقدّم، خلفية باهتة)
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_inverse: str
    primary: str
    primary_hover: str
    primary_pressed: str
    primary_soft: str
    primary_soft_text: str
    danger: str
    danger_hover: str
    danger_soft: str
    danger_soft_text: str
    success_soft: str
    success_soft_text: str
    warning_soft: str
    warning_soft_text: str
    disabled_bg: str
    disabled_text: str
    selection: str
    selection_text: str
    group_row: str      # خلفية صف المجموعة في الشجرة
    code_bg: str
    code_text: str


LIGHT = Palette(
    dark=False,
    bg="#F1F4F9",
    surface="#FFFFFF",
    surface_alt="#F7F9FC",
    surface_sunken="#E8EDF4",
    border="#E2E8F0",
    border_strong="#CBD5E1",
    text="#182230",
    text_muted="#64748B",
    text_inverse="#FFFFFF",
    primary="#2563EB",
    primary_hover="#1D4ED8",
    primary_pressed="#1E40AF",
    primary_soft="#EAF1FE",
    primary_soft_text="#1D4ED8",
    danger="#DC2626",
    danger_hover="#B91C1C",
    danger_soft="#FEF0F0",
    danger_soft_text="#B42318",
    success_soft="#ECFDF3",
    success_soft_text="#067647",
    warning_soft="#FFF8EB",
    warning_soft_text="#B54708",
    disabled_bg="#F1F4F9",
    disabled_text="#A3AEBF",
    selection="#DCE8FD",
    selection_text="#12294F",
    group_row="#EEF2F8",
    code_bg="#1B1F27",
    code_text="#D7DCE5",
)

DARK = Palette(
    dark=True,
    bg="#0F1218",
    surface="#171B22",
    surface_alt="#1D222B",
    surface_sunken="#242A35",
    border="#2A303B",
    border_strong="#3A424F",
    text="#E6EAF2",
    text_muted="#94A3B8",
    text_inverse="#FFFFFF",
    primary="#3B82F6",
    primary_hover="#60A5FA",
    primary_pressed="#2563EB",
    primary_soft="#1B2941",
    primary_soft_text="#93C5FD",
    danger="#E5484D",
    danger_hover="#F16A6E",
    danger_soft="#2E1A1C",
    danger_soft_text="#FCA5A5",
    success_soft="#132A1F",
    success_soft_text="#6EE7A8",
    warning_soft="#2C2114",
    warning_soft_text="#FCC58A",
    disabled_bg="#1B2029",
    disabled_text="#5B6675",
    selection="#24395C",
    selection_text="#E6EAF2",
    group_row="#1F2531",
    code_bg="#0B0E13",
    code_text="#C9D1DC",
)

# ألوان تمييز المجموعات — تُستخدم كنقطة/مربّع صغير لا كخلفية للصف كله،
# فيبقى تمييز المجموعات واضحاً دون أن تتحول الشجرة إلى قوس قزح.
GROUP_ACCENTS_LIGHT = [
    "#2563EB", "#0E9F6E", "#D97706", "#7C3AED", "#0891B2",
    "#DC2626", "#65A30D", "#DB2777", "#4F46E5", "#B45309",
]
GROUP_ACCENTS_DARK = [
    "#60A5FA", "#34D399", "#FBBF24", "#A78BFA", "#22D3EE",
    "#F87171", "#A3E635", "#F472B6", "#818CF8", "#FCD34D",
]


def palette(dark: bool) -> Palette:
    return DARK if dark else LIGHT


def group_accents(dark: bool) -> list[str]:
    return GROUP_ACCENTS_DARK if dark else GROUP_ACCENTS_LIGHT


def stylesheet(dark: bool) -> str:
    """QSS كامل للتطبيق مبنيّ من رموز الوضع المطلوب."""
    p = palette(dark)
    chevron_down = icons.qss_asset("chevron-down", p.text_muted, 12)
    chevron_up = icons.qss_asset("chevron-up", p.text_muted, 12)
    branch_closed = icons.qss_asset("chevron-left", p.text_muted, 13)
    branch_open = icons.qss_asset("chevron-down", p.text_muted, 13)
    check_mark = icons.qss_asset("check", p.text_inverse, 13)
    dash_mark = icons.qss_asset("minus", p.text_inverse, 13)

    def image(path: str) -> str:
        return f"image: url({path});" if path else ""

    return f"""
* {{ outline: 0; }}

QWidget {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {p.text};
}}
QMainWindow, QDialog {{ background: {p.bg}; }}

QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_SM}px;
    padding: 6px 9px;
}}

/* ── شريط القوائم والقوائم ───────────────────────────────────────── */
QMenuBar {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: 3px 6px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 11px;
    border-radius: {RADIUS_SM}px;
}}
QMenuBar::item:selected, QMenuBar::item:pressed {{
    background: {p.primary_soft};
    color: {p.primary_soft_text};
}}
QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: {SPACE_XS}px;
}}
QMenu::item {{
    padding: 7px 14px;
    border-radius: {RADIUS_SM}px;
    min-width: 180px;
}}
QMenu::item:selected {{ background: {p.primary_soft}; color: {p.primary_soft_text}; }}
QMenu::item:disabled {{ color: {p.disabled_text}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
QMenu::icon {{ padding-right: 6px; }}

/* ── شريط الأدوات ────────────────────────────────────────────────── */
QToolBar {{
    background: {p.surface};
    border: 0;
    border-bottom: 1px solid {p.border};
    padding: {SPACE_XS}px {SPACE_SM}px;
    spacing: {SPACE_XS}px;
}}
QToolBar::separator {{ width: 1px; background: {p.border}; margin: 5px 7px; }}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: 6px 10px;
    color: {p.text};
    font-weight: 500;
}}
QToolButton:hover {{ background: {p.surface_alt}; border-color: {p.border}; }}
QToolButton:pressed {{ background: {p.surface_sunken}; }}
QToolButton:checked {{
    background: {p.primary_soft};
    color: {p.primary_soft_text};
    border-color: {p.primary_soft};
}}
QToolButton:disabled {{ color: {p.disabled_text}; }}
QToolButton#iconOnly {{ padding: 6px; }}

/* ── البطاقات ────────────────────────────────────────────────────── */
QFrame#card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_LG}px;
}}
QFrame#actionBar {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_LG}px;
}}
QFrame#separator {{ background: {p.border}; border: 0; }}
QLabel#cardTitle {{
    font-size: 12px;
    font-weight: 700;
    color: {p.text_muted};
}}
QLabel#hint {{ color: {p.text_muted}; font-size: 12px; }}
QLabel#emptyTitle {{ font-size: 15px; font-weight: 700; color: {p.text}; }}
QLabel#emptyHint {{ font-size: 12px; color: {p.text_muted}; }}
QLabel#statValue {{ font-size: 14px; font-weight: 700; color: {p.text}; }}
QLabel#statLabel {{ font-size: 11px; color: {p.text_muted}; }}
QLabel#selectionSummary {{ font-size: 13px; font-weight: 600; color: {p.text}; }}
QLabel#fieldLabel {{ color: {p.text_muted}; font-size: 12px; }}
QLabel#fieldValue {{ color: {p.text}; font-size: 12px; }}

QFrame#statChip {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
}}
QFrame#thumbBox {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
}}

/* ── الأزرار ─────────────────────────────────────────────────────── */
QPushButton {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_SM}px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {p.surface_alt}; border-color: {p.text_muted}; }}
QPushButton:pressed {{ background: {p.surface_sunken}; }}
QPushButton:focus {{ border-color: {p.primary}; }}
QPushButton:disabled {{
    background: {p.disabled_bg};
    color: {p.disabled_text};
    border-color: {p.border};
}}
QPushButton[variant="primary"] {{
    background: {p.primary};
    color: {p.text_inverse};
    border-color: {p.primary};
}}
QPushButton[variant="primary"]:hover {{
    background: {p.primary_hover};
    border-color: {p.primary_hover};
}}
QPushButton[variant="primary"]:pressed {{ background: {p.primary_pressed}; }}
QPushButton[variant="primary"]:disabled {{
    background: {p.disabled_bg};
    color: {p.disabled_text};
    border-color: {p.border};
}}
QPushButton[variant="danger"] {{
    background: {p.danger};
    color: {p.text_inverse};
    border-color: {p.danger};
}}
QPushButton[variant="danger"]:hover {{
    background: {p.danger_hover};
    border-color: {p.danger_hover};
}}
QPushButton[variant="danger"]:disabled {{
    background: {p.disabled_bg};
    color: {p.disabled_text};
    border-color: {p.border};
}}
QPushButton[variant="ghost"] {{
    background: transparent;
    border-color: transparent;
    color: {p.text_muted};
    font-weight: 500;
}}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_alt}; color: {p.text}; }}
QPushButton[variant="ghost"]:disabled {{
    background: transparent;
    border-color: transparent;
    color: {p.disabled_text};
}}
QPushButton[size="cta"] {{ padding: 11px 24px; font-size: 14px; }}

/* ── الحقول ──────────────────────────────────────────────────────── */
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_SM}px;
    padding: 7px 10px;
    selection-background-color: {p.primary};
    selection-color: {p.text_inverse};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QComboBox:focus, QTextEdit:focus {{ border-color: {p.primary}; }}
QLineEdit:read-only {{ background: {p.surface_alt}; }}
QLineEdit:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
    background: {p.disabled_bg};
    color: {p.disabled_text};
}}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox::down-arrow {{ {image(chevron_down)} width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: {SPACE_XS}px;
    selection-background-color: {p.primary_soft};
    selection-color: {p.primary_soft_text};
}}
QDoubleSpinBox::up-button, QSpinBox::up-button,
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    background: transparent;
    border: 0;
    width: 18px;
}}
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {{
    {image(chevron_up)} width: 11px; height: 11px;
}}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {{
    {image(chevron_down)} width: 11px; height: 11px;
}}

/* ── مؤشرات الاختيار ─────────────────────────────────────────────── */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTreeView::indicator {{
    width: 17px;
    height: 17px;
    border: 1px solid {p.border_strong};
    border-radius: {RADIUS_XS}px;
    background: {p.surface};
}}
QCheckBox::indicator:hover, QTreeView::indicator:hover {{ border-color: {p.primary}; }}
QCheckBox::indicator:checked, QTreeView::indicator:checked {{
    background: {p.primary};
    border-color: {p.primary};
    {image(check_mark)}
}}
QCheckBox::indicator:indeterminate, QTreeView::indicator:indeterminate {{
    background: {p.primary};
    border-color: {p.primary};
    {image(dash_mark)}
}}
QCheckBox::indicator:disabled, QTreeView::indicator:disabled {{
    background: {p.disabled_bg};
    border-color: {p.border};
}}

/* ── الشجرة والقوائم ─────────────────────────────────────────────── */
QTreeWidget, QTreeView, QListWidget, QListView {{
    background: {p.surface};
    alternate-background-color: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: 2px;
}}
QTreeView::item, QListView::item {{
    min-height: 25px;
    padding: 3px 4px;
    border: 0;
    color: {p.text};
}}
QTreeView::item:hover, QListView::item:hover {{ background: {p.primary_soft}; }}
QTreeView::item:selected, QListView::item:selected {{
    background: {p.selection};
    color: {p.selection_text};
}}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    {image(branch_closed)}
}}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{
    {image(branch_open)}
}}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.text_muted};
    padding: 8px 10px;
    border: 0;
    border-bottom: 1px solid {p.border};
    font-size: 12px;
    font-weight: 700;
}}
QHeaderView::section:hover {{ color: {p.text}; }}

/* منطقة التمرير شفافة لتظهر خلفية البطاقة من تحتها */
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ── أشرطة التمرير ───────────────────────────────────────────────── */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p.border_strong};
    border-radius: 5px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:hover {{ background: {p.text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ── التقدّم وشريط الحالة ────────────────────────────────────────── */
QProgressBar {{
    background: {p.surface_sunken};
    border: 0;
    border-radius: 5px;
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {p.primary}; border-radius: 5px; }}
QStatusBar {{
    background: {p.surface};
    color: {p.text_muted};
    border-top: 1px solid {p.border};
}}
QStatusBar::item {{ border: 0; }}
QStatusBar QLabel {{ color: {p.text_muted}; }}

/* ── المقسّمات واللوحات ──────────────────────────────────────────── */
QSplitter::handle {{ background: transparent; }}
QSplitter::handle:horizontal {{ width: {SPACE_MD}px; }}
QSplitter::handle:vertical {{ height: {SPACE_MD}px; }}
QDockWidget {{ color: {p.text}; titlebar-close-icon: none; titlebar-normal-icon: none; }}
QDockWidget::title {{
    background: {p.surface_alt};
    color: {p.text_muted};
    padding: 7px 12px;
    border-top: 1px solid {p.border};
    border-bottom: 1px solid {p.border};
    font-weight: 700;
    text-align: center;
}}

/* ── ملصقات دلالية ───────────────────────────────────────────────── */
QLabel#warningBox {{
    background: {p.warning_soft};
    color: {p.warning_soft_text};
    border: 1px solid {p.warning_soft_text}40;
    border-radius: {RADIUS_MD}px;
    padding: 10px 12px;
}}
QLabel#dangerBox {{
    background: {p.danger_soft};
    color: {p.danger_soft_text};
    border: 1px solid {p.danger_soft_text}40;
    border-radius: {RADIUS_MD}px;
    padding: 10px 12px;
}}
QLabel#infoBox {{
    background: {p.primary_soft};
    color: {p.primary_soft_text};
    border: 1px solid {p.primary_soft_text}33;
    border-radius: {RADIUS_MD}px;
    padding: 10px 12px;
}}
QLabel#successBox {{
    background: {p.success_soft};
    color: {p.success_soft_text};
    border: 1px solid {p.success_soft_text}40;
    border-radius: {RADIUS_MD}px;
    padding: 10px 12px;
}}
QLabel#dryRunSummary {{
    background: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: {SPACE_MD}px;
}}
QLabel#statsBox {{
    background: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    padding: 10px;
    font-weight: 600;
}}

/* ── سجل النشاط ──────────────────────────────────────────────────── */
/* الخط الأساسي عربي مشكول الحروف؛ الطوابع الزمنية وحدها أحادية العرض
   (داخل span في log_message) فتبقى الأعمدة مصطفّة والعربية متصلة. */
QTextEdit#logView {{
    background: {p.code_bg};
    color: {p.code_text};
    border: 1px solid {p.border};
    border-radius: {RADIUS_MD}px;
    font-size: 12px;
    padding: {SPACE_SM}px;
}}
"""


def qt_palette(dark: bool) -> QPalette:
    """``QPalette`` مطابقة للرموز — تضمن اتساق ما يرسمه Qt بنفسه."""
    p = palette(dark)
    qp = QPalette()
    qp.setColor(QPalette.Window, QColor(p.bg))
    qp.setColor(QPalette.WindowText, QColor(p.text))
    qp.setColor(QPalette.Base, QColor(p.surface))
    qp.setColor(QPalette.AlternateBase, QColor(p.surface_alt))
    qp.setColor(QPalette.Text, QColor(p.text))
    qp.setColor(QPalette.PlaceholderText, QColor(p.text_muted))
    qp.setColor(QPalette.Button, QColor(p.surface))
    qp.setColor(QPalette.ButtonText, QColor(p.text))
    qp.setColor(QPalette.BrightText, QColor(p.danger))
    # لون التحديد الهادئ هو نفسه في QSS و QPalette، وإلا ظهرت مساحة البادئة
    # في الشجرة (التي يرسمها Qt لا QSS) بلون أساسي صارخ داخل الصف المحدد.
    qp.setColor(QPalette.Highlight, QColor(p.selection))
    qp.setColor(QPalette.HighlightedText, QColor(p.selection_text))
    qp.setColor(QPalette.Link, QColor(p.primary))
    qp.setColor(QPalette.ToolTipBase, QColor(p.surface))
    qp.setColor(QPalette.ToolTipText, QColor(p.text))
    qp.setColor(QPalette.Mid, QColor(p.border_strong))
    qp.setColor(QPalette.Dark, QColor(p.border_strong))
    qp.setColor(QPalette.Light, QColor(p.surface_alt))
    for role in (
        QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.Base
    ):
        qp.setColor(QPalette.Disabled, role, QColor(p.disabled_text))
    return qp
