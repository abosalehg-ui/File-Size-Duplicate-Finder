"""عناصر واجهة قابلة لإعادة الاستخدام — بنية موحّدة للبطاقات والحالات.

الهدف من فصلها: النافذة الرئيسية تصف *ترتيب* الواجهة فقط، أمّا شكل البطاقة
أو رقاقة الإحصاء فيُعرَّف مرة واحدة هنا، فلا يتكرر تنسيق يدوي في كل موضع.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from . import icons, theme


def apply_variant(button: QPushButton, variant: str = "", size: str = "") -> QPushButton:
    """إسناد نوع الزر (primary / danger / ghost) ليأخذ تنسيقه من QSS.

    نستخدم خصائص Qt بدل ``setStyleSheet`` لكل زر، حتى تبقى الألوان في
    مكان واحد وتتبدّل مع الثيم.
    """
    if variant:
        button.setProperty("variant", variant)
    if size:
        button.setProperty("size", size)
    return button


class Card(QFrame):
    """بطاقة بيضاء بعنوان صغير ومحتوى — بديل ``QGroupBox`` ولافتته العائمة."""

    def __init__(
        self, title: str = "", icon_name: str = "",
        compact: bool = False, parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("card")
        pad = theme.SPACE_SM if compact else theme.SPACE_MD
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_LG, pad, theme.SPACE_LG, pad)
        outer.setSpacing(pad)

        self._icon_name = icon_name if title else ""
        self._title_icon: QLabel | None = None
        if title:
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_SM)
            self._title_icon = QLabel()
            self._title_icon.setFixedSize(theme.ICON_SM, theme.ICON_SM)
            row.addWidget(self._title_icon)
            label = QLabel(title)
            label.setObjectName("cardTitle")
            row.addWidget(label)
            row.addStretch(1)
            outer.addLayout(row)

        self.body = QVBoxLayout()
        self.body.setSpacing(pad)
        outer.addLayout(self.body, 1)

    def retheme(self, dark: bool) -> None:
        if self._title_icon is not None and self._icon_name:
            p = theme.palette(dark)
            self._title_icon.setPixmap(
                icons.pixmap(self._icon_name, p.text_muted, theme.ICON_SM)
            )


class StatChip(QFrame):
    """رقاقة إحصاء: أيقونة + قيمة + وصف — تُقرأ بلمحة بدل سطر نصي طويل."""

    def __init__(self, icon_name: str, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statChip")
        self._icon_name = icon_name
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_MD, 6, theme.SPACE_MD, 6)
        layout.setSpacing(theme.SPACE_SM)

        self._icon = QLabel()
        self._icon.setFixedSize(theme.ICON_MD, theme.ICON_MD)
        layout.addWidget(self._icon, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self._value = QLabel("—")
        self._value.setObjectName("statValue")
        self._label = QLabel(label)
        self._label.setObjectName("statLabel")
        text_col.addWidget(self._value)
        text_col.addWidget(self._label)
        layout.addLayout(text_col, 1)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def retheme(self, dark: bool, accent: str = "") -> None:
        p = theme.palette(dark)
        self._icon.setPixmap(
            icons.pixmap(self._icon_name, accent or p.text_muted, theme.ICON_MD)
        )


class EmptyState(QWidget):
    """حالة فارغة: أيقونة كبيرة + عنوان + تلميح + زر إجراء اختياري.

    وجودها يمنع الشاشة البيضاء المحيّرة قبل أول بحث أو عند انعدام النتائج.
    """

    action_clicked = pyqtSignal()

    def __init__(self, icon_name: str, title: str, hint: str, action: str = "", parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(theme.SPACE_SM)

        self._icon = QLabel()
        self._icon.setFixedSize(44, 44)
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon, 0, Qt.AlignHCenter)

        self._title = QLabel(title)
        self._title.setObjectName("emptyTitle")
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)

        self._hint = QLabel(hint)
        self._hint.setObjectName("emptyHint")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setMaximumWidth(420)
        layout.addWidget(self._hint, 0, Qt.AlignHCenter)

        self.button: QPushButton | None = None
        if action:
            self.button = apply_variant(QPushButton(action), "primary")
            self.button.clicked.connect(self.action_clicked)
            layout.addSpacing(theme.SPACE_XS)
            layout.addWidget(self.button, 0, Qt.AlignHCenter)

    def set_content(self, icon_name: str, title: str, hint: str) -> None:
        self._icon_name = icon_name
        self._title.setText(title)
        self._hint.setText(hint)

    def retheme(self, dark: bool) -> None:
        p = theme.palette(dark)
        self._icon.setPixmap(icons.pixmap(self._icon_name, p.border_strong, 40))
        if self.button is not None:
            self.button.setIcon(
                icons.icon("folder-open", p.text_inverse, theme.ICON_SM)
            )


class FieldRow(QWidget):
    """سطر «تسمية: قيمة» — لتفاصيل المعاينة، بقيمة قابلة للتحديد والنسخ."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_SM)
        self._label = QLabel(label)
        self._label.setObjectName("fieldLabel")
        self._label.setMinimumWidth(74)
        self._label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        layout.addWidget(self._label, 0)
        self._value = QLabel("—")
        self._value.setObjectName("fieldValue")
        self._value.setWordWrap(True)
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._value, 1)

    def set_value(self, value: str, tooltip: str = "") -> None:
        self._value.setText(value or "—")
        self._value.setToolTip(tooltip or value)
