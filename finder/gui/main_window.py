"""النافذة الرئيسية للتطبيق.

تنظيم الواجهة في ثلاث مناطق واضحة تتبع تدفّق العمل:

1. **بطاقة البحث** (أعلى) — أين نبحث وكيف، ومعها الإجراء الأساسي الوحيد.
2. **النتائج** (الوسط) — إحصاءات، فلترة، شجرة المجموعات، ولوحة معاينة جانبية.
3. **شريط الإجراءات** (أسفل) — ما يُفعل بالتحديد، ويظل معطّلاً حتى يوجد تحديد فعلي.

القوائم وشريط الأدوات يحملان الإجراءات العامة (الثيم، السجل، الإرجاع،
التصدير) فلا تتزاحم مع مسار العمل الأساسي.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QSettings, QSize, Qt, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QDockWidget,
    QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QSplitter, QStackedWidget, QStatusBar,
    QToolBar, QToolButton, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..core import (
    DEFAULT_EXCLUDE_DIRS, HashCache, format_bytes, group_by_size, scan_folder,
)
from ..core.hashing import MODE_FULL, MODE_PARTIAL, MODE_SIZE, refine_groups_by_hash
from ..ops.history import HistoryStore
from ..ops.operations import (
    OUTPUT_DIR_NAME, TRASH_AVAILABLE, move_groups, restore_batch, trash_groups,
)
from . import icons, textfmt, theme
from .dialogs import AboutDialog, DryRunDialog, GuideDialog, HistoryDialog
from .selection import (
    STATE_CHECKED, STATE_PARTIAL, group_tristate, partition_keep_one,
)
from .widgets import Card, EmptyState, FieldRow, StatChip, apply_variant
from .workers import Worker

# عدد المجموعات الذي نتوقف بعده عن التوسيع التلقائي حفاظاً على استجابة الشجرة
AUTO_EXPAND_GROUP_LIMIT = 100

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg"}

SORT_ROLE = Qt.UserRole + 1

# وصف كل وضع كشف — يظهر تحت الخيارات فلا يحتاج المستخدم لتخمين الفرق
MODE_HINTS = {
    MODE_SIZE: "يقارن الأحجام فقط — الأسرع، لكنه لا يضمن تطابق المحتوى.",
    MODE_PARTIAL: "نفس الحجم + بصمة من بداية الملف ونهايته — توازن جيد بين السرعة والدقة.",
    MODE_FULL: "بصمة SHA-256 كاملة — أبطأ، لكنه يضمن التطابق الفعلي دون استثناء.",
}


def _assets_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):  # داخل حزمة PyInstaller
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parents[2] / "assets"


def load_app_icon() -> QIcon:
    for name in ("icon.ico", "icon.png", os.path.join("icons", "icon_256.png")):
        path = _assets_dir() / name
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def _file_times(path: str) -> tuple[str | None, str | None]:
    """(تاريخ الإنشاء إن توفر بدقة، تاريخ آخر تعديل).

    st_ctime على غير Windows هو وقت تغيير الـ inode لا الإنشاء،
    لذا لا نعرضه كإنشاء إلا حيث يكون صحيحاً.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None, None
    fmt = "%Y-%m-%d %H:%M"
    modified = datetime.fromtimestamp(st.st_mtime).strftime(fmt)
    created = None
    if sys.platform.startswith("win"):
        created = datetime.fromtimestamp(st.st_ctime).strftime(fmt)
    elif hasattr(st, "st_birthtime"):
        created = datetime.fromtimestamp(st.st_birthtime).strftime(fmt)
    return created, modified


class SortableItem(QTreeWidgetItem):
    """صف يقبل الترتيب بالقيمة الحقيقية لا بالنص.

    بدونه يرتّب Qt عمود الحجم أبجدياً فيأتي «9 KB» بعد «10 MB».
    """

    def __lt__(self, other: QTreeWidgetItem) -> bool:  # type: ignore[override]
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        mine = self.data(column, SORT_ROLE)
        theirs = other.data(column, SORT_ROLE)
        if mine is not None and theirs is not None:
            return mine < theirs
        return self.text(column).lower() < other.text(column).lower()


class FileSizeDuplicateFinder(QMainWindow):
    """النافذة الرئيسية."""

    def __init__(self):
        super().__init__()
        self.similar_groups: list[list[dict]] = []
        self._workers: list[Worker] = []
        self._updating_checks = False
        self._busy = False
        self._scan_root = ""
        self._current_preview: dict | None = None
        # كل عنصر يحمل أيقونة يُسجَّل هنا ليُعاد تلوينه عند تبديل الثيم
        self._icon_targets: list[tuple[object, str, str, int]] = []
        self._rethemable: list[object] = []
        self.settings = QSettings("FileSizeDuplicateFinder", "Settings")
        self.dark_mode = self.settings.value("dark_mode", False, type=bool)
        self.history_store = HistoryStore()

        self.setAcceptDrops(True)
        self.init_ui()
        self.load_settings()
        self.apply_theme()

    # ── سحب وإفلات ───────────────────────────────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and os.path.isdir(url.toLocalFile()):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if os.path.isdir(path):
                    self.folder_input.setText(path)
                    self.settings.setValue("last_folder", path)
                    self.log_message(f"تم تعيين المجلد عبر السحب: {path}")
                    self.status_bar.showMessage(f"المجلد: {path}", 4000)
                    event.acceptProposedAction()
                    return
        event.ignore()

    # ── بناء الواجهة ─────────────────────────────────────────────────────
    def init_ui(self):
        self.setWindowTitle(f"{APP_NAME} — v{__version__}")
        self.setWindowIcon(load_app_icon())
        self.setMinimumSize(1040, 700)
        self.resize(1240, 820)
        self.setLayoutDirection(Qt.RightToLeft)

        self._build_actions()
        self._build_menubar()
        self._build_toolbar()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_MD, theme.SPACE_LG, theme.SPACE_MD
        )
        root.setSpacing(theme.SPACE_MD)

        root.addWidget(self._build_search_card())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_results_card())   # يمين (RTL)
        splitter.addWidget(self._build_preview_card())   # يسار
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([840, 330])
        self.splitter = splitter
        root.addWidget(splitter, 1)

        root.addWidget(self._build_action_bar())

        self._build_log_dock()
        self._build_status_bar()
        self._update_mode_hint()
        self._show_placeholder("initial")
        self._update_selection_state()
        self.folder_input.setFocus()

    # ── الإجراءات (مصدر واحد للقوائم وشريط الأدوات والاختصارات) ─────────
    def _act(
        self, text: str, icon_name: str, slot, shortcut: str = "",
        tip: str = "", checkable: bool = False, role: str = "text",
    ) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.WindowShortcut)
        action.setToolTip(f"{tip or text} ({shortcut})" if shortcut else (tip or text))
        action.setStatusTip(tip or text)
        action.setCheckable(checkable)
        if checkable:
            action.toggled.connect(slot)
        else:
            action.triggered.connect(slot)
        self._reg_icon(action, icon_name, role, theme.ICON_SM)
        return action

    def _reg_icon(self, target, name: str, role: str = "text", size: int = theme.ICON_SM):
        """تسجيل عنصر ليأخذ أيقونته من الثيم ويُعاد تلوينها عند تبديله."""
        self._icon_targets.append((target, name, role, size))
        return target

    def _build_actions(self):
        self.act_browse = self._act(
            "اختيار مجلد…", "folder-open", self.browse_folder, "Ctrl+O",
            "اختيار المجلد الذي سيُفحص",
        )
        self.act_search = self._act(
            "بدء البحث", "search", self.start_search, "F5",
            "بدء فحص المجلد بالإعدادات الحالية",
        )
        self.act_stop = self._act(
            "إيقاف", "stop", self.stop_current_worker, "Esc", "إيقاف العملية الجارية",
            role="danger",
        )
        self.act_stop.setEnabled(False)
        self.act_export = self._act(
            "تصدير التقرير…", "download", self.export_report, "Ctrl+S",
            "حفظ النتائج بصيغة TXT أو CSV أو JSON",
        )
        self.act_quit = self._act("خروج", "power", self.close, "Ctrl+Q")

        self.act_select_all = self._act(
            "تحديد كل الظاهر", "check-square", self.select_all, "Ctrl+A",
            "تحديد كل الملفات الظاهرة في النتائج",
        )
        self.act_deselect_all = self._act(
            "إلغاء التحديد", "square", self.deselect_all, "Ctrl+D",
        )
        self.act_keep_newest = self._act(
            "تحديد الكل عدا الأحدث", "wand",
            lambda: self.smart_select("newest"), "Ctrl+Shift+N",
            "في كل مجموعة يُحدَّد الكل ما عدا أحدث ملف — تبقى نسخة دائماً",
        )
        self.act_keep_oldest = self._act(
            "تحديد الكل عدا الأقدم", "wand",
            lambda: self.smart_select("oldest"), "Ctrl+Shift+B",
            "في كل مجموعة يُحدَّد الكل ما عدا أقدم ملف — تبقى نسخة دائماً",
        )
        self.act_move = self._act(
            "عزل المحدد في مجلد…", "archive", self.move_files, "Ctrl+M",
            "نقل الملفات المحددة إلى مجلد منظّم داخل مجلد البحث",
        )
        self.act_trash = self._act(
            "إرسال المحدد إلى سلة المحذوفات", "trash", self.move_to_trash,
            "Ctrl+Shift+Del", "إرسال الملفات المحددة إلى سلة محذوفات النظام",
            role="danger",
        )
        self.act_restore = self._act(
            "سجل العمليات والإرجاع…", "undo", self.show_history_dialog, "Ctrl+H",
            "استعراض العمليات السابقة وإرجاع الملفات إلى مواقعها",
        )

        self.act_focus_filter = self._act(
            "تصفية النتائج", "filter", self._focus_filter, "Ctrl+F",
        )
        self.act_expand = self._act(
            "توسيع كل المجموعات", "expand", self.expand_all_groups, "Ctrl+Shift+E",
        )
        self.act_collapse = self._act(
            "طيّ كل المجموعات", "collapse", self.collapse_all_groups, "Ctrl+Shift+W",
        )
        self.act_dark = self._act(
            "الوضع الداكن", "moon", self.set_dark_mode, "Ctrl+T",
            "تبديل بين الوضع الفاتح والداكن", checkable=True,
        )
        self.act_dark.setChecked(self.dark_mode)
        self.act_log = self._act(
            "سجل النشاط", "terminal", self._toggle_log_dock, "Ctrl+L",
            "إظهار أو إخفاء لوحة سجل النشاط", checkable=True,
        )
        self.act_preview = self._act(
            "لوحة المعاينة", "eye", self._toggle_preview, "Ctrl+P",
            "إظهار أو إخفاء لوحة معاينة الملف", checkable=True,
        )
        self.act_preview.setChecked(True)

        self.act_guide = self._act(
            "دليل الاستخدام", "help", self.show_guide, "F1",
            "شرح أوضاع الكشف وضمانات الأمان",
        )
        self.act_about = self._act("حول التطبيق", "info", self.show_about)

    def _build_menubar(self):
        bar = self.menuBar()

        file_menu = bar.addMenu("ملف")
        file_menu.addAction(self.act_browse)
        file_menu.addSeparator()
        file_menu.addAction(self.act_search)
        file_menu.addAction(self.act_stop)
        file_menu.addSeparator()
        file_menu.addAction(self.act_export)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        select_menu = bar.addMenu("التحديد")
        select_menu.addAction(self.act_select_all)
        select_menu.addAction(self.act_deselect_all)
        select_menu.addSeparator()
        select_menu.addAction(self.act_keep_newest)
        select_menu.addAction(self.act_keep_oldest)

        actions_menu = bar.addMenu("الإجراءات")
        actions_menu.addAction(self.act_move)
        actions_menu.addAction(self.act_trash)
        actions_menu.addSeparator()
        actions_menu.addAction(self.act_restore)

        view_menu = bar.addMenu("عرض")
        view_menu.addAction(self.act_focus_filter)
        view_menu.addSeparator()
        view_menu.addAction(self.act_expand)
        view_menu.addAction(self.act_collapse)
        view_menu.addSeparator()
        view_menu.addAction(self.act_preview)
        view_menu.addAction(self.act_log)
        view_menu.addSeparator()
        view_menu.addAction(self.act_dark)

        help_menu = bar.addMenu("مساعدة")
        help_menu.addAction(self.act_guide)
        help_menu.addAction(self.act_about)

    def _build_toolbar(self):
        bar = QToolBar("شريط الأدوات")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(theme.ICON_MD, theme.ICON_MD))
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.addAction(self.act_browse)
        bar.addAction(self.act_restore)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        bar.addAction(self.act_log)
        bar.addAction(self.act_dark)
        bar.addAction(self.act_guide)
        for action in (self.act_log, self.act_dark, self.act_guide):
            button = bar.widgetForAction(action)
            if button is not None:
                button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                button.setObjectName("iconOnly")
        self.addToolBar(Qt.TopToolBarArea, bar)
        self.toolbar = bar

    # ── بطاقة البحث ──────────────────────────────────────────────────────
    def _build_search_card(self) -> QWidget:
        card = Card("نطاق البحث", "sliders", compact=True)
        self._rethemable.append(card)
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_SM)
        grid.setVerticalSpacing(theme.SPACE_SM)

        folder_label = QLabel("المجلد")
        folder_label.setObjectName("fieldLabel")
        folder_label.setMinimumWidth(52)
        self.folder_input = QLineEdit()
        self.folder_input.setObjectName("pathInput")
        self.folder_input.setPlaceholderText(
            "الصق مساراً، أو اسحب مجلداً إلى النافذة، أو اضغط «استعراض»…"
        )
        self.folder_input.setAccessibleName("مسار مجلد البحث")
        self.folder_input.setClearButtonEnabled(True)
        self.folder_input.setMinimumHeight(34)
        self.folder_input.returnPressed.connect(self.start_search)

        self.browse_btn = QPushButton("استعراض")
        self.browse_btn.clicked.connect(self.browse_folder)
        self.browse_btn.setToolTip("اختيار مجلد البحث (Ctrl+O)")
        self._reg_icon(self.browse_btn, "folder-open", "text", theme.ICON_SM)
        browse_btn = self.browse_btn

        self.search_btn = apply_variant(QPushButton("بدء البحث"), "primary", "cta")
        self.search_btn.setMinimumHeight(46)
        self.search_btn.setMinimumWidth(168)
        self.search_btn.setAccessibleName("بدء البحث")
        self.search_btn.setToolTip("بدء البحث (F5)")
        self.search_btn.clicked.connect(self._on_primary_clicked)
        self._reg_icon(self.search_btn, "search", "inverse", theme.ICON_MD)

        grid.addWidget(folder_label, 0, 0)
        grid.addWidget(self.folder_input, 0, 1)
        grid.addWidget(browse_btn, 0, 2)
        grid.addLayout(self._build_options_row(), 1, 0, 1, 3)
        grid.addWidget(self.search_btn, 0, 3, 2, 1)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)

        self.mode_hint = QLabel()
        self.mode_hint.setObjectName("hint")
        self.mode_hint.setWordWrap(True)
        hint_row = QHBoxLayout()
        hint_row.setSpacing(theme.SPACE_SM)
        self.mode_hint_icon = QLabel()
        self.mode_hint_icon.setFixedSize(theme.ICON_SM, theme.ICON_SM)
        hint_row.addWidget(self.mode_hint_icon, 0, Qt.AlignTop)
        hint_row.addWidget(self.mode_hint, 1)
        card.body.addLayout(hint_row)
        return card

    def _build_options_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_SM)

        mode_label = QLabel("وضع الكشف")
        mode_label.setObjectName("fieldLabel")
        self.detect_mode_combo = QComboBox()
        self.detect_mode_combo.addItem("حجم متقارب — سريع", MODE_SIZE)
        self.detect_mode_combo.addItem("بصمة جزئية — متوازن", MODE_PARTIAL)
        self.detect_mode_combo.addItem("SHA-256 كامل — دقيق", MODE_FULL)
        self.detect_mode_combo.setCurrentIndex(1)
        self.detect_mode_combo.setMinimumWidth(196)
        self.detect_mode_combo.setAccessibleName("وضع كشف التكرار")
        self.detect_mode_combo.currentIndexChanged.connect(self._update_mode_hint)
        row.addWidget(mode_label)
        row.addWidget(self.detect_mode_combo)

        row.addWidget(self._vline())

        self.recursive_check = QCheckBox("المجلدات الفرعية")
        self.recursive_check.setToolTip(
            "فحص كل المجلدات الفرعية — تُتجاهل المجلدات النظامية "
            "مثل .git و node_modules و venv"
        )
        row.addWidget(self.recursive_check)

        self.same_ext_check = QCheckBox("نفس الامتداد فقط")
        self.same_ext_check.setToolTip(
            "لا تُجمَّع الملفات إلا إذا اتفقت في الامتداد (‎.jpg مع ‎.jpg)"
        )
        row.addWidget(self.same_ext_check)

        row.addWidget(self._vline())

        threshold_label = QLabel("حد التقارب")
        threshold_label.setObjectName("fieldLabel")
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1000)   # 0 = تطابق حجم دقيق
        self.threshold_spin.setValue(0.0)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setSuffix(" م.ب")
        self.threshold_spin.setMinimumWidth(104)
        self.threshold_spin.setAccessibleName("حد التقارب بالميجابايت")
        self.threshold_spin.setToolTip(
            "الفرق المسموح بين أحجام الملفات. 0 يعني تطابق حجم دقيق."
        )
        self.threshold_spin.valueChanged.connect(self._update_mode_hint)
        row.addWidget(threshold_label)
        row.addWidget(self.threshold_spin)
        row.addStretch(1)
        return row

    def _vline(self) -> QFrame:
        line = QFrame()
        line.setObjectName("separator")
        line.setFixedWidth(1)
        line.setMinimumHeight(22)
        return line

    def _update_mode_hint(self, *_):
        mode = self.detect_mode_combo.currentData() or MODE_SIZE
        text = MODE_HINTS.get(mode, "")
        if mode != MODE_SIZE and self.threshold_spin.value() > 0:
            text += "  •  يُستحسن ترك حد التقارب على 0 مع أوضاع البصمة."
        self.mode_hint.setText(text)

    # ── بطاقة النتائج ────────────────────────────────────────────────────
    def _build_results_card(self) -> QWidget:
        # العنوان ورقائق الإحصاء في صف واحد — يوفّر الطول للشجرة وهي الأهم
        card = Card(compact=True)

        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_SM)
        self.results_title_icon = QLabel()
        self.results_title_icon.setFixedSize(theme.ICON_SM, theme.ICON_SM)
        header.addWidget(self.results_title_icon)
        results_title = QLabel("النتائج")
        results_title.setObjectName("cardTitle")
        header.addWidget(results_title)
        header.addSpacing(theme.SPACE_SM)

        self.stat_groups = StatChip("layers", "مجموعة مكررة")
        self.stat_files = StatChip("copy", "ملف داخل المجموعات")
        self.stat_size = StatChip("hard-drive", "الحجم الكلي")
        self.stat_savings = StatChip("savings", "يمكن تحريره")
        self.stat_chips = [
            self.stat_groups, self.stat_files, self.stat_size, self.stat_savings
        ]
        for chip in self.stat_chips:
            header.addWidget(chip, 1)
        card.body.addLayout(header)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(theme.SPACE_SM)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(
            "تصفية بالاسم أو الامتداد — العمليات تنطبق على الظاهر فقط (Ctrl+F)"
        )
        self.filter_input.setAccessibleName("فلترة النتائج")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self.apply_results_filter)
        self._filter_icon = QAction(self)
        self.filter_input.addAction(self._filter_icon, QLineEdit.LeadingPosition)
        self._reg_icon(self._filter_icon, "filter", "muted", theme.ICON_SM)
        filter_row.addWidget(self.filter_input, 1)

        self.filter_status = QLabel("")
        self.filter_status.setObjectName("hint")
        filter_row.addWidget(self.filter_status)

        for action in (self.act_expand, self.act_collapse):
            button = QToolButton()
            button.setObjectName("iconOnly")
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            filter_row.addWidget(button)
        card.body.addLayout(filter_row)

        self.results_stack = QStackedWidget()
        # حدّ أدنى متحفظ: لو ضاق الطول تتقلّص الشجرة بدل أن تزحف على ما تحتها
        self.results_stack.setMinimumHeight(120)
        self.results_tree = self._build_tree()
        self.placeholder = EmptyState("search", "", "", "استعراض مجلد")
        self.placeholder.action_clicked.connect(self.browse_folder)
        self._rethemable.append(self.placeholder)
        self.results_stack.addWidget(self.placeholder)
        self.results_stack.addWidget(self.results_tree)
        card.body.addWidget(self.results_stack, 1)

        card.body.addLayout(self._build_select_row())
        return card

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(["", "الملف", "الحجم", "النوع", "المجلد"])
        tree.setAccessibleName("نتائج مجموعات الملفات المتقاربة")
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setRootIsDecorated(True)
        tree.setExpandsOnDoubleClick(False)
        tree.setSortingEnabled(True)
        tree.setIndentation(16)
        tree.itemChanged.connect(self.on_item_check_changed)
        tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        tree.itemDoubleClicked.connect(self.open_file_location)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self.show_context_menu)

        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSortIndicatorShown(True)
        header.setStretchLastSection(False)
        tree.setColumnWidth(0, 46)
        tree.setColumnWidth(4, 230)
        return tree

    def _build_select_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_SM)
        for action in (
            self.act_select_all, self.act_deselect_all,
            self.act_keep_newest, self.act_keep_oldest,
        ):
            button = QPushButton(action.text().replace("تحديد الكل عدا", "الكل عدا"))
            self._bind(button, action)
            self._reg_icon(button, self._icon_name_of(action), "text", theme.ICON_SM)
            row.addWidget(button)
        row.addStretch(1)
        export_btn = apply_variant(QPushButton("تصدير التقرير"), "ghost")
        self._bind(export_btn, self.act_export)
        self._reg_icon(export_btn, "download", "muted", theme.ICON_SM)
        row.addWidget(export_btn)
        return row

    def _bind(self, button: QPushButton, action: QAction) -> QPushButton:
        """ربط زر بإجراء: نفس النقر ونفس التلميح ونفس حالة التعطيل.

        بدون هذا الربط يبقى الزر نشطاً بينما إجراؤه معطّل، فيضغطه المستخدم
        ولا يحدث شيء.
        """
        button.setToolTip(action.toolTip())
        button.clicked.connect(action.trigger)
        button.setEnabled(action.isEnabled())
        action.changed.connect(
            lambda b=button, a=action: b.setEnabled(a.isEnabled())
        )
        return button

    def _icon_name_of(self, action: QAction) -> str:
        for target, name, _role, _size in self._icon_targets:
            if target is action:
                return name
        return ""

    # ── لوحة المعاينة ────────────────────────────────────────────────────
    def _build_preview_card(self) -> QWidget:
        card = Card("معاينة الملف", "eye")
        self._rethemable.append(card)
        self.preview_stack = QStackedWidget()

        self.preview_empty = EmptyState(
            "eye", "لا ملف محدد", "اختر صفّ ملف من النتائج لعرض تفاصيله هنا."
        )
        self._rethemable.append(self.preview_empty)
        self.preview_stack.addWidget(self.preview_empty)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(theme.SPACE_MD)

        thumb_box = QFrame()
        thumb_box.setObjectName("thumbBox")
        thumb_box.setFixedHeight(146)
        thumb_layout = QVBoxLayout(thumb_box)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_thumb = QLabel()
        self.preview_thumb.setAlignment(Qt.AlignCenter)
        thumb_layout.addWidget(self.preview_thumb)
        details_layout.addWidget(thumb_box)

        self.preview_fields = {
            "name": FieldRow("الاسم"),
            "size": FieldRow("الحجم"),
            "ext": FieldRow("النوع"),
            "modified": FieldRow("آخر تعديل"),
            "created": FieldRow("الإنشاء"),
            "dir": FieldRow("المجلد"),
        }
        for field in self.preview_fields.values():
            details_layout.addWidget(field)
        details_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE_SM)
        open_btn = QPushButton("فتح الموقع")
        open_btn.clicked.connect(self._open_current_location)
        self._reg_icon(open_btn, "external", "text", theme.ICON_SM)
        copy_btn = apply_variant(QPushButton("نسخ المسار"), "ghost")
        copy_btn.clicked.connect(self._copy_current_path)
        self._reg_icon(copy_btn, "copy", "muted", theme.ICON_SM)
        buttons.addWidget(open_btn, 1)
        buttons.addWidget(copy_btn, 1)
        details_layout.addLayout(buttons)

        self.preview_stack.addWidget(details)
        card.body.addWidget(self.preview_stack, 1)
        self.preview_card = card
        return card

    # ── شريط الإجراءات السفلي ────────────────────────────────────────────
    def _build_action_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("actionBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(theme.SPACE_LG, 6, theme.SPACE_LG, 6)
        layout.setSpacing(theme.SPACE_MD)

        self.selection_icon = QLabel()
        self.selection_icon.setFixedSize(theme.ICON_MD, theme.ICON_MD)
        layout.addWidget(self.selection_icon)

        self.selection_summary = QLabel()
        self.selection_summary.setObjectName("selectionSummary")
        layout.addWidget(self.selection_summary)

        self.keep_one_warning = QLabel()
        self.keep_one_warning.setObjectName("hint")
        self.keep_one_warning.setVisible(False)
        layout.addWidget(self.keep_one_warning)
        layout.addStretch(1)

        self.move_btn = apply_variant(QPushButton("عزل المحدد"), "primary")
        self.move_btn.setToolTip(self.act_move.toolTip())
        self.move_btn.clicked.connect(self.move_files)
        self._reg_icon(self.move_btn, "archive", "inverse", theme.ICON_SM)

        self.trash_btn = apply_variant(QPushButton("سلة المحذوفات"), "danger")
        self.trash_btn.clicked.connect(self.move_to_trash)
        self.trash_btn.setToolTip(
            self.act_trash.toolTip() if TRASH_AVAILABLE
            else "غير متوفر — ثبّت الحزمة send2trash"
        )
        self._reg_icon(self.trash_btn, "trash", "inverse", theme.ICON_SM)

        layout.addWidget(self.move_btn)
        layout.addWidget(self.trash_btn)
        self.action_bar = bar
        return bar

    # ── لوحة سجل النشاط ──────────────────────────────────────────────────
    def _build_log_dock(self):
        self.log_text = QTextEdit()
        self.log_text.setObjectName("logView")
        self.log_text.setReadOnly(True)
        self.log_text.setAccessibleName("سجل النشاط")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM
        )
        layout.setSpacing(theme.SPACE_SM)
        layout.addWidget(self.log_text, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save_btn = apply_variant(QPushButton("حفظ السجل"), "ghost")
        save_btn.clicked.connect(self.save_log)
        self._reg_icon(save_btn, "download", "muted", theme.ICON_SM)
        clear_btn = apply_variant(QPushButton("مسح"), "ghost")
        clear_btn.clicked.connect(self.log_text.clear)
        self._reg_icon(clear_btn, "x", "muted", theme.ICON_SM)
        buttons.addWidget(save_btn)
        buttons.addWidget(clear_btn)
        layout.addLayout(buttons)

        dock = QDockWidget("سجل النشاط", self)
        dock.setObjectName("logDock")
        dock.setAllowedAreas(Qt.BottomDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetClosable)
        dock.setWidget(content)
        dock.setMinimumHeight(150)
        dock.hide()
        dock.visibilityChanged.connect(self._on_log_visibility)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.log_dock = dock

    def _toggle_log_dock(self, visible: bool):
        self.log_dock.setVisible(visible)

    def _on_log_visibility(self, visible: bool):
        if self.act_log.isChecked() != visible:
            self.act_log.setChecked(visible)

    def _toggle_preview(self, visible: bool):
        # قد يُستدعى أثناء البناء قبل إنشاء البطاقة (عند ضبط الحالة الابتدائية)
        if hasattr(self, "preview_card"):
            self.preview_card.setVisible(visible)

    # ── شريط الحالة ──────────────────────────────────────────────────────
    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.progress_label = QLabel("")
        self.progress_label.setObjectName("hint")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(210)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setVisible(False)

        self.status_bar.addPermanentWidget(self.progress_label)
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.status_bar.showMessage("جاهز")

    # ── الثيم ────────────────────────────────────────────────────────────
    def _role_color(self, role: str) -> str:
        p = theme.palette(self.dark_mode)
        return {
            "text": p.text,
            "muted": p.text_muted,
            "inverse": p.text_inverse,
            "danger": p.danger,
            "primary": p.primary,
        }.get(role, p.text)

    def apply_theme(self):
        """تطبيق الثيم على التطبيق كله: QSS + QPalette + كل الأيقونات."""
        app = QApplication.instance()
        if app is not None:
            app.setPalette(theme.qt_palette(self.dark_mode))
            app.setStyleSheet(theme.stylesheet(self.dark_mode))

        p = theme.palette(self.dark_mode)
        for target, name, role, size in self._icon_targets:
            target.setIcon(
                icons.icon(name, self._role_color(role), size, p.disabled_text)
            )
        for widget in self._rethemable:
            widget.retheme(self.dark_mode)
        for chip, accent in zip(
            self.stat_chips,
            (p.primary, p.text_muted, p.text_muted, p.success_soft_text),
        ):
            chip.retheme(self.dark_mode, accent)

        self.act_dark.setText("الوضع الفاتح" if self.dark_mode else "الوضع الداكن")
        self._retarget_icon(self.act_dark, "sun" if self.dark_mode else "moon")
        self.mode_hint_icon.setPixmap(
            icons.pixmap("info", p.text_muted, theme.ICON_SM)
        )
        self.results_title_icon.setPixmap(
            icons.pixmap("layers", p.text_muted, theme.ICON_SM)
        )
        self.selection_icon.setPixmap(
            icons.pixmap("check-square", p.text_muted, theme.ICON_MD)
        )
        self._style_group_rows()
        self._refresh_preview_visuals()

    def _retarget_icon(self, action: QAction, name: str):
        """تغيير أيقونة إجراء مسجّل (مثل تبديل القمر/الشمس)."""
        p = theme.palette(self.dark_mode)
        for index, (target, _name, role, size) in enumerate(self._icon_targets):
            if target is action:
                self._icon_targets[index] = (target, name, role, size)
                action.setIcon(
                    icons.icon(name, self._role_color(role), size, p.disabled_text)
                )
                return

    def set_dark_mode(self, enabled: bool):
        if enabled == self.dark_mode:
            return
        self.dark_mode = enabled
        self.settings.setValue("dark_mode", enabled)
        self.apply_theme()
        self.log_message(
            "تم التبديل إلى الوضع الداكن" if enabled else "تم التبديل إلى الوضع الفاتح"
        )

    # ── السجل النصي ──────────────────────────────────────────────────────
    def log_message(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "#58a6ff", "SUCCESS": "#3fb950",
            "WARNING": "#d29922", "ERROR": "#f85149",
        }
        p = theme.palette(self.dark_mode)
        color = colors.get(level, p.code_text)
        prefix_font = f"font-family: {theme.MONO_STACK};"
        self.log_text.insertHtml(
            f'<span style="{prefix_font} color: {p.text_muted};">[{timestamp}]</span> '
            f'<span style="{prefix_font} color: {color};">[{level}]</span> '
            f'<span style="color: {p.code_text};">{message}</span><br>'
        )
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def save_log(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "حفظ السجل",
            f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt)",
        )
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toPlainText())
            self.log_message(f"تم حفظ السجل: {file_path}", "SUCCESS")

    # ── إدارة الخيوط ─────────────────────────────────────────────────────
    def _spawn(self, job, on_done, on_error=None, on_cancelled=None) -> Worker:
        worker = Worker(job)
        worker.progress.connect(self.on_progress)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_error or self._on_generic_error)
        if on_cancelled is not None:
            worker.cancelled.connect(on_cancelled)
        worker.finished.connect(lambda: self._workers.remove(worker)
                                if worker in self._workers else None)
        self._workers.append(worker)
        worker.start()
        return worker

    def stop_current_worker(self):
        if not self._busy:
            return
        for worker in self._workers:
            if worker.isRunning():
                worker.stop()
        self.progress_label.setText("جاري الإيقاف…")

    def _on_primary_clicked(self):
        """الزر الأساسي يتحول إلى «إيقاف» أثناء العمل — إجراء واحد في مكان واحد."""
        if self._busy:
            self.stop_current_worker()
        else:
            self.start_search()

    def _on_generic_error(self, error: str):
        QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء العملية:\n{error}")
        self.log_message(f"خطأ: {error}", "ERROR")
        self._set_busy(False)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.act_search.setEnabled(not busy)
        self.act_stop.setEnabled(busy)
        self.act_browse.setEnabled(not busy)
        self.act_restore.setEnabled(not busy)
        self.folder_input.setEnabled(not busy)
        self.browse_btn.setEnabled(not busy)
        self.detect_mode_combo.setEnabled(not busy)
        self.threshold_spin.setEnabled(not busy)
        self.recursive_check.setEnabled(not busy)
        self.same_ext_check.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.search_btn.setText("إيقاف")
            apply_variant(self.search_btn, "danger", "cta")
            self._retarget_button_icon(self.search_btn, "stop")
        else:
            self.search_btn.setText("بدء البحث")
            apply_variant(self.search_btn, "primary", "cta")
            self._retarget_button_icon(self.search_btn, "search")
            self.progress_label.setText("")
        self.search_btn.style().unpolish(self.search_btn)
        self.search_btn.style().polish(self.search_btn)
        self._update_selection_state()

    def _retarget_button_icon(self, button: QPushButton, name: str):
        p = theme.palette(self.dark_mode)
        for index, (target, _name, role, size) in enumerate(self._icon_targets):
            if target is button:
                self._icon_targets[index] = (target, name, role, size)
                button.setIcon(
                    icons.icon(name, self._role_color(role), size, p.disabled_text)
                )
                return

    def on_progress(self, value: int, message: str):
        # الرسالة تُعرض في ملصق التقدّم فقط — لا تُكرَّر في شريط الحالة
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)

    # ── البحث ────────────────────────────────────────────────────────────
    def browse_folder(self):
        last_folder = self.folder_input.text() or self.settings.value("last_folder", "")
        folder = QFileDialog.getExistingDirectory(
            self, "اختر المجلد", last_folder,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks,
        )
        if folder:
            self.folder_input.setText(folder)
            self.settings.setValue("last_folder", folder)
            self.log_message(f"تم اختيار المجلد: {folder}")

    def _content_warning(self) -> str:
        """رسالة تحذير إن كان وضع الكشف الحالي لا يضمن تطابق المحتوى.

        - وضع الحجم: يقارن الأحجام فقط.
        - وضع partial: توقيع من بداية ونهاية الملف — قد يعطي تطابقاً كاذباً
          لملفات كبيرة لا تختلف إلا في وسطها. الضمان الكامل في وضع SHA-256.
        فارغة ("") في وضع full لأنه مطابقة مؤكدة.
        """
        mode = self.detect_mode_combo.currentData() or MODE_SIZE
        if mode == MODE_SIZE:
            return (
                "<b>وضع الكشف الحالي يقارن الأحجام فقط</b> — تقارب الحجم لا يعني "
                "تطابق المحتوى. للتأكد من التكرار الفعلي استخدم بصمة جزئية أو SHA-256."
            )
        if mode == MODE_PARTIAL:
            return (
                "<b>البصمة الجزئية تقارن بداية الملف ونهايته فقط</b> — قد تظهر ملفات "
                "كبيرة تختلف في وسطها كأنها متطابقة. للتأكد التام استخدم SHA-256."
            )
        return ""

    def start_search(self):
        if self._busy:
            return
        folder = self.folder_input.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(
                self, "مجلد غير صالح",
                "لم يُحدَّد مجلد صالح للبحث.\nاختر مجلداً موجوداً ثم أعد المحاولة.",
            )
            self.folder_input.setFocus()
            return

        self.settings.setValue("last_folder", folder)
        self._scan_root = folder
        self.results_tree.clear()
        self.similar_groups = []
        self._clear_preview()
        self._reset_stats()
        self.progress_bar.setValue(0)
        self._set_busy(True)
        self._show_placeholder("searching")
        self.log_message("بدء البحث عن الملفات المتقاربة…")

        threshold_bytes = int(self.threshold_spin.value() * 1024 * 1024)
        same_ext = self.same_ext_check.isChecked()
        recursive = self.recursive_check.isChecked()
        mode = self.detect_mode_combo.currentData() or MODE_SIZE

        def job(progress, cancel):
            def scan_progress(n):
                progress(min(45, 5 + n // 500), f"جاري فحص الملفات… ({n} ملف)")

            files = scan_folder(
                folder, recursive=recursive, exclude_dirs=DEFAULT_EXCLUDE_DIRS,
                cancel=cancel, progress=scan_progress,
            )
            progress(48, f"تحليل {len(files)} ملف بخوارزمية النافذة المنزلقة…")
            groups = group_by_size(
                files, threshold_bytes=threshold_bytes,
                same_ext_only=same_ext, cancel=cancel,
            )
            if mode in (MODE_PARTIAL, MODE_FULL) and groups:
                with HashCache() as cache:
                    def hash_progress(done, total, label):
                        if mode == MODE_FULL and label == "Partial hash":
                            pct = 50 + done * 25 // max(total, 1)
                        elif label == "Partial hash":
                            pct = 50 + done * 50 // max(total, 1)
                        else:
                            pct = 75 + done * 25 // max(total, 1)
                        progress(pct, f"حساب {label}… ({done}/{total})")

                    groups = refine_groups_by_hash(
                        groups, use_full=(mode == MODE_FULL), cache=cache,
                        cancel=cancel, progress=hash_progress,
                    )
                    cache.prune_missing(limit=5000)
            return groups

        self._spawn(job, self.on_search_finished,
                    on_cancelled=self.on_search_cancelled)

    def on_search_finished(self, groups: list):
        self.similar_groups = groups
        self.display_results(groups)
        self._set_busy(False)
        self.progress_bar.setValue(100)
        self.status_bar.showMessage(
            f"اكتمل البحث — {len(groups)} مجموعة" if groups
            else "اكتمل البحث — لا مجموعات مطابقة", 6000
        )
        QApplication.beep()
        self.log_message(
            f"اكتمل البحث — تم العثور على {len(groups)} مجموعة", "SUCCESS"
        )

    def on_search_cancelled(self):
        self._set_busy(False)
        self.status_bar.showMessage("تم إيقاف البحث", 5000)
        self._show_placeholder("initial")
        self.log_message("تم إيقاف البحث", "WARNING")

    # ── عرض النتائج والتحديد ─────────────────────────────────────────────
    def _display_dir(self, path: str) -> str:
        """مجلد الملف نسبةً إلى جِذر الفحص — أقصر وأسهل مقارنةً."""
        directory = os.path.dirname(path)
        if self._scan_root:
            try:
                relative = os.path.relpath(directory, self._scan_root)
            except ValueError:
                return directory
            return "." if relative == "." else relative
        return directory

    def display_results(self, groups: list):
        p = theme.palette(self.dark_mode)
        self.results_tree.blockSignals(True)
        self.results_tree.setUpdatesEnabled(False)
        was_sorting = self.results_tree.isSortingEnabled()
        self.results_tree.setSortingEnabled(False)
        try:
            self.results_tree.clear()
            total_files = 0
            total_size = 0
            potential_savings = 0
            expand = len(groups) <= AUTO_EXPAND_GROUP_LIMIT

            for group_idx, group_files in enumerate(groups):
                group_item = SortableItem(self.results_tree)
                group_item.setFlags(group_item.flags() | Qt.ItemIsUserCheckable)
                group_item.setCheckState(0, Qt.Unchecked)
                group_size = sum(f["size"] for f in group_files)
                by_size = sorted(group_files, key=lambda x: x["size"], reverse=True)
                savings = sum(f["size"] for f in by_size[1:])
                potential_savings += savings

                group_item.setText(
                    1,
                    f"مجموعة {textfmt.num(group_idx + 1)} — "
                    f"{textfmt.count_files(len(group_files))}",
                )
                group_item.setData(1, SORT_ROLE, group_idx)
                group_item.setText(2, textfmt.ltr(format_bytes(group_size)))
                group_item.setData(2, SORT_ROLE, group_size)
                extensions = {f["ext"].lower() for f in group_files}
                group_item.setText(
                    3,
                    textfmt.ltr(extensions.pop()) or "بدون"
                    if len(extensions) == 1 else "متعدد",
                )
                group_item.setText(
                    4, f"يمكن تحرير {textfmt.ltr(format_bytes(savings))}"
                )
                group_item.setData(4, SORT_ROLE, savings)
                group_item.setToolTip(
                    1,
                    f"{textfmt.count_files(len(group_files))} متطابقة — "
                    f"يمكن تحرير {textfmt.ltr(format_bytes(savings))}",
                )
                group_item.setExpanded(expand)

                for file_info in group_files:
                    file_item = SortableItem(group_item)
                    file_item.setFlags(file_item.flags() | Qt.ItemIsUserCheckable)
                    file_item.setCheckState(0, Qt.Unchecked)
                    # المسارات والأحجام تُعزل اتجاهياً كي لا تُقلبها الواجهة RTL
                    file_item.setText(1, textfmt.ltr(file_info["name"]))
                    file_item.setData(1, SORT_ROLE, file_info["name"].lower())
                    file_item.setText(2, textfmt.ltr(format_bytes(file_info["size"])))
                    file_item.setData(2, SORT_ROLE, file_info["size"])
                    file_item.setText(3, textfmt.ltr(file_info["ext"]) or "بدون")
                    directory = self._display_dir(file_info["path"])
                    file_item.setText(4, textfmt.ltr(directory))
                    file_item.setData(4, SORT_ROLE, directory.lower())
                    file_item.setData(0, Qt.UserRole, file_info)
                    file_item.setToolTip(1, file_info["path"])
                    file_item.setToolTip(4, os.path.dirname(file_info["path"]))
                    is_image = file_info.get("ext", "").lower() in IMAGE_EXTS
                    file_item.setIcon(
                        1,
                        icons.icon(
                            "image" if is_image else "file", p.text_muted, theme.ICON_SM
                        ),
                    )
                    total_files += 1
                    total_size += file_info["size"]

            self.stat_groups.set_value(f"{len(groups)}")
            self.stat_files.set_value(f"{total_files}")
            self.stat_size.set_value(textfmt.ltr(format_bytes(total_size)))
            self.stat_savings.set_value(textfmt.ltr(format_bytes(potential_savings)))
        finally:
            self.results_tree.setSortingEnabled(was_sorting)
            self.results_tree.setUpdatesEnabled(True)
            self.results_tree.blockSignals(False)

        self._style_group_rows()
        if self.filter_input.text():
            self.apply_results_filter(self.filter_input.text())
        else:
            self._show_results_or_placeholder()
        self._update_selection_state()

    def _reset_stats(self):
        for chip in self.stat_chips:
            chip.set_value("—")
        self.filter_status.setText("")

    def _style_group_rows(self):
        """تمييز صفوف المجموعات: خلفية موحّدة + خط عريض + مربّع لون صغير.

        مربّع اللون يفصل المجموعات بصرياً دون تلوين الصف كله، فتبقى الشجرة
        هادئة ويبقى النص مقروءاً في الوضعين.
        """
        if not hasattr(self, "results_tree"):
            return
        p = theme.palette(self.dark_mode)
        accents = theme.group_accents(self.dark_mode)
        row_bg = QColor(p.group_row)
        text_color = QColor(p.text)
        bold = QFont()
        bold.setBold(True)
        root = self.results_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_item = root.child(i)
            group_item.setIcon(1, QIcon(icons.swatch(accents[i % len(accents)])))
            for col in range(self.results_tree.columnCount()):
                group_item.setBackground(col, row_bg)
                group_item.setForeground(col, text_color)
                group_item.setFont(col, bold)
            group_item.setForeground(4, QColor(p.text_muted))
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                child.setForeground(4, QColor(p.text_muted))
                is_image = (child.data(0, Qt.UserRole) or {}).get(
                    "ext", ""
                ).lower() in IMAGE_EXTS
                child.setIcon(
                    1,
                    icons.icon(
                        "image" if is_image else "file", p.text_muted, theme.ICON_SM
                    ),
                )

    # ── الحالات الفارغة ──────────────────────────────────────────────────
    def _show_placeholder(self, kind: str):
        content = {
            "initial": (
                "search", "لم يبدأ البحث بعد",
                "اختر مجلداً ثم اضغط «بدء البحث» — أو اسحب المجلد إلى النافذة مباشرة.",
            ),
            "searching": (
                "clock", "جاري الفحص…",
                "يمكنك الإيقاف في أي لحظة، والنتائج ستظهر هنا عند الانتهاء.",
            ),
            "empty": (
                "shield", "لا توجد ملفات مكررة",
                "لم تُطابِق أي ملفات المعايير الحالية. جرّب تفعيل «المجلدات الفرعية» "
                "أو رفع حد التقارب أو تبديل وضع الكشف.",
            ),
            "filtered": (
                "filter", "لا نتائج للفلتر",
                "لا مجموعة تطابق نص التصفية الحالي. امسح الفلتر لعرض كل النتائج.",
            ),
        }[kind]
        self.placeholder.set_content(*content)
        self.placeholder.retheme(self.dark_mode)
        if self.placeholder.button is not None:
            self.placeholder.button.setVisible(kind == "initial")
        self.results_stack.setCurrentWidget(self.placeholder)

    def _show_results_or_placeholder(self):
        if not self.similar_groups:
            self._show_placeholder("empty" if self._scan_root else "initial")
            return
        root = self.results_tree.invisibleRootItem()
        visible = any(
            not root.child(i).isHidden() for i in range(root.childCount())
        )
        if visible:
            self.results_stack.setCurrentWidget(self.results_tree)
        else:
            self._show_placeholder("filtered")

    def expand_all_groups(self):
        self.results_tree.expandAll()

    def collapse_all_groups(self):
        self.results_tree.collapseAll()

    def _focus_filter(self):
        self.filter_input.setFocus()
        self.filter_input.selectAll()

    def apply_results_filter(self, text: str):
        text = (text or "").strip().lower()
        root = self.results_tree.invisibleRootItem()
        total = root.childCount()
        shown = 0
        for i in range(total):
            group_item = root.child(i)
            any_visible = False
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if not text:
                    child.setHidden(False)
                    any_visible = True
                else:
                    match = (text in child.text(1).lower()
                             or text in child.text(3).lower())
                    child.setHidden(not match)
                    any_visible = any_visible or match
            group_item.setHidden(bool(text) and not any_visible)
            shown += int(not group_item.isHidden())
        self.filter_status.setText(
            f"{textfmt.num(shown)} من {textfmt.num(total)} مجموعة"
            if text and total else ""
        )
        self._show_results_or_placeholder()
        self._update_selection_state()

    def on_item_check_changed(self, item: QTreeWidgetItem, column: int):
        """مزامنة حالة المجموعة/الملفات. تحديد مجموعة يشمل ملفاتها
        الظاهرة فقط — الصفوف المخفية بالفلتر لا تُمس أبداً."""
        if column != 0 or self._updating_checks:
            return
        self._updating_checks = True
        try:
            if item.parent() is None:
                state = item.checkState(0)
                if state != Qt.PartiallyChecked:
                    for j in range(item.childCount()):
                        child = item.child(j)
                        if not child.isHidden():
                            child.setCheckState(0, state)
            else:
                self._sync_group_state(item.parent())
        finally:
            self._updating_checks = False
        self._update_selection_state()

    def _sync_group_state(self, group_item: QTreeWidgetItem):
        visible = checked = 0
        for j in range(group_item.childCount()):
            child = group_item.child(j)
            if child.isHidden():
                continue
            visible += 1
            if child.checkState(0) == Qt.Checked:
                checked += 1
        # قرار الحالة الثلاثية في وحدة نقية مُختبَرة (selection.group_tristate)
        state = group_tristate(visible, checked)
        qt_state = {
            STATE_CHECKED: Qt.Checked,
            STATE_PARTIAL: Qt.PartiallyChecked,
        }.get(state, Qt.Unchecked)
        group_item.setCheckState(0, qt_state)

    def _set_all_checks(self, state):
        self._updating_checks = True
        self.results_tree.setUpdatesEnabled(False)
        try:
            root = self.results_tree.invisibleRootItem()
            for i in range(root.childCount()):
                group = root.child(i)
                if group.isHidden():
                    continue
                for j in range(group.childCount()):
                    child = group.child(j)
                    if not child.isHidden():
                        child.setCheckState(0, state)
                self._sync_group_state(group)
        finally:
            self.results_tree.setUpdatesEnabled(True)
            self._updating_checks = False
        self._update_selection_state()

    def select_all(self):
        # Ctrl+A داخل حقل نصي يجب أن يظل «تحديد النص» لا «تحديد كل الملفات»
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.selectAll()
            return
        self._set_all_checks(Qt.Checked)

    def deselect_all(self):
        self._set_all_checks(Qt.Unchecked)

    def smart_select(self, keep: str = "newest"):
        """تحديد كل ملفات كل مجموعة ظاهرة ما عدا واحد يُحتفظ به
        (الأحدث أو الأقدم تعديلاً) — فتبقى نسخة دائماً."""
        self._updating_checks = True
        self.results_tree.setUpdatesEnabled(False)
        try:
            root = self.results_tree.invisibleRootItem()
            for i in range(root.childCount()):
                group = root.child(i)
                if group.isHidden():
                    continue
                visible = [
                    group.child(j) for j in range(group.childCount())
                    if not group.child(j).isHidden()
                ]
                # القرار في وحدة نقية مُختبَرة: أي الملفات تُحدَّد وأيّها يبقى.
                # نطابق بهوية العنصر (id) لأن قواميس الملفات قد تتساوى قيمةً.
                infos = [(c, c.data(0, Qt.UserRole) or {}) for c in visible]
                to_select, _kept = partition_keep_one(
                    [info for _c, info in infos], keep=keep
                )
                select_ids = {id(info) for info in to_select}
                for child, info in infos:
                    child.setCheckState(
                        0, Qt.Checked if id(info) in select_ids else Qt.Unchecked
                    )
                self._sync_group_state(group)
        finally:
            self.results_tree.setUpdatesEnabled(True)
            self._updating_checks = False
        label = "الأحدث" if keep == "newest" else "الأقدم"
        self._update_selection_state()
        self.log_message(f"تحديد ذكي: كل الملفات عدا {label} في كل مجموعة")
        self.status_bar.showMessage(f"تم تحديد كل الملفات عدا {label} في كل مجموعة", 5000)

    def get_selected(self) -> tuple[list[list[dict]], int]:
        """(المجموعات المحددة، عدد المجموعات المحدد كل ملفاتها).

        تُحتسب فقط العناصر الظاهرة (غير المخفية بالفلتر) — ما لا يراه
        المستخدم لا يدخل في أي عملية.
        """
        selected_groups: list[list[dict]] = []
        fully_selected = 0
        root = self.results_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            if group.isHidden():
                continue
            files = []
            for j in range(group.childCount()):
                child = group.child(j)
                if child.isHidden():
                    continue
                if child.checkState(0) == Qt.Checked:
                    info = child.data(0, Qt.UserRole)
                    if info:
                        files.append(info)
            if files:
                selected_groups.append(files)
                if len(files) == group.childCount():
                    fully_selected += 1
        return selected_groups, fully_selected

    def _update_selection_state(self):
        """تحديث شريط الإجراءات ليصف التحديد الحالي بدقة.

        الأزرار المدمّرة تبقى معطّلة حتى يوجد تحديد فعلي — أفضل من السماح
        بالضغط ثم إظهار «الرجاء التحديد».
        """
        selected, fully = self.get_selected()
        count = sum(len(group) for group in selected)
        size = sum(f["size"] for group in selected for f in group)

        if count:
            self.selection_summary.setText(
                f"محدد: {textfmt.count_files(count)} في "
                f"{textfmt.count_groups(len(selected))} · "
                f"{textfmt.ltr(format_bytes(size))}"
            )
        else:
            self.selection_summary.setText("لم تحدد أي ملف بعد")

        p = theme.palette(self.dark_mode)
        self.selection_icon.setPixmap(
            icons.pixmap(
                "check-square" if count else "square",
                p.primary if count else p.text_muted,
                theme.ICON_MD,
            )
        )
        if fully:
            self.keep_one_warning.setText(
                f"⚠ كل ملفات {fully} مجموعة محددة — لن تبقى نسخة"
            )
            self.keep_one_warning.setStyleSheet(f"color: {p.danger};")
            self.keep_one_warning.setVisible(True)
        else:
            self.keep_one_warning.setVisible(False)

        enabled = bool(count) and not self._busy
        self.move_btn.setEnabled(enabled)
        self.trash_btn.setEnabled(enabled and TRASH_AVAILABLE)
        self.act_move.setEnabled(enabled)
        self.act_trash.setEnabled(enabled and TRASH_AVAILABLE)
        has_results = bool(self.similar_groups)
        for action in (
            self.act_select_all, self.act_deselect_all,
            self.act_keep_newest, self.act_keep_oldest,
            self.act_export, self.act_expand, self.act_collapse,
            self.act_focus_filter,
        ):
            action.setEnabled(has_results and not self._busy)
        self.filter_input.setEnabled(has_results and not self._busy)

    # ── المعاينة والقوائم ────────────────────────────────────────────────
    def on_tree_selection_changed(self):
        items = self.results_tree.selectedItems()
        info = items[0].data(0, Qt.UserRole) if items else None
        if not info:
            self._clear_preview()
            return
        self._current_preview = info
        created, modified = _file_times(info["path"])
        fields = self.preview_fields
        fields["name"].set_value(textfmt.ltr(info["name"]), info["path"])
        fields["size"].set_value(textfmt.ltr(format_bytes(info["size"])))
        fields["ext"].set_value(textfmt.ltr(info["ext"]) or "بدون امتداد")
        fields["modified"].set_value(textfmt.ltr(modified or "") or "—")
        fields["created"].set_value(textfmt.ltr(created or "") or "—")
        fields["created"].setVisible(bool(created))
        directory = os.path.dirname(info["path"])
        fields["dir"].set_value(
            textfmt.ltr(self._display_dir(info["path"])), directory
        )
        self.preview_stack.setCurrentIndex(1)
        self._refresh_preview_visuals()

    def _clear_preview(self):
        self._current_preview = None
        if hasattr(self, "preview_stack"):
            self.preview_stack.setCurrentIndex(0)

    def _refresh_preview_visuals(self):
        if not hasattr(self, "preview_thumb"):
            return
        info = self._current_preview
        if not info:
            return
        p = theme.palette(self.dark_mode)
        path, ext = info["path"], info.get("ext", "")
        if ext.lower() in IMAGE_EXTS and os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self.preview_thumb.setPixmap(
                    pix.scaled(200, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self.preview_thumb.setPixmap(icons.pixmap("file", p.border_strong, 46))

    def _open_current_location(self):
        if self._current_preview:
            self._open_folder_of(self._current_preview["path"])

    def _copy_current_path(self):
        if not self._current_preview:
            return
        QApplication.clipboard().setText(self._current_preview["path"])
        self.status_bar.showMessage("تم نسخ مسار الملف", 3000)

    def _open_folder_of(self, path: str):
        folder = os.path.dirname(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self.log_message(f"فتح المجلد: {folder}")

    def open_file_location(self, item: QTreeWidgetItem, column: int):
        info = item.data(0, Qt.UserRole)
        if info:
            self._open_folder_of(info["path"])
        else:
            item.setExpanded(not item.isExpanded())

    def show_context_menu(self, position):
        item = self.results_tree.itemAt(position)
        if item is None:
            return
        p = theme.palette(self.dark_mode)
        menu = QMenu(self)
        info = item.data(0, Qt.UserRole)
        if info:
            open_action = menu.addAction(
                icons.icon("external", p.text, theme.ICON_SM), "فتح موقع الملف"
            )
            open_action.triggered.connect(lambda: self._open_folder_of(info["path"]))
            copy_action = menu.addAction(
                icons.icon("copy", p.text, theme.ICON_SM), "نسخ المسار"
            )
            copy_action.triggered.connect(
                lambda: QApplication.clipboard().setText(info["path"])
            )
            menu.addSeparator()
            checked = item.checkState(0) == Qt.Checked
            toggle = menu.addAction(
                icons.icon("square" if checked else "check-square", p.text, theme.ICON_SM),
                "إلغاء تحديد هذا الملف" if checked else "تحديد هذا الملف",
            )
            toggle.triggered.connect(
                lambda: item.setCheckState(0, Qt.Unchecked if checked else Qt.Checked)
            )
        else:
            group_checked = item.checkState(0) == Qt.Checked
            toggle = menu.addAction(
                icons.icon(
                    "square" if group_checked else "check-square", p.text, theme.ICON_SM
                ),
                "إلغاء تحديد المجموعة" if group_checked else "تحديد المجموعة كلها",
            )
            toggle.triggered.connect(
                lambda: item.setCheckState(
                    0, Qt.Unchecked if group_checked else Qt.Checked
                )
            )
            expand = menu.addAction(
                icons.icon(
                    "collapse" if item.isExpanded() else "expand", p.text, theme.ICON_SM
                ),
                "طيّ المجموعة" if item.isExpanded() else "توسيع المجموعة",
            )
            expand.triggered.connect(lambda: item.setExpanded(not item.isExpanded()))
        menu.exec_(self.results_tree.viewport().mapToGlobal(position))

    # ── النقل ────────────────────────────────────────────────────────────
    def move_files(self):
        selected, fully_selected = self.get_selected()
        if not selected:
            return

        dlg = DryRunDialog(
            selected, "عزل إلى مجلد",
            fully_selected_groups=fully_selected,
            content_warning=self._content_warning(),
            dark_mode=self.dark_mode,
            parent=self,
        )
        dlg.exec_()
        if not dlg.confirmed:
            self.log_message("تم إلغاء العملية من نافذة المعاينة")
            return

        folder = self._scan_root or self.folder_input.text()
        total_files = sum(len(g) for g in selected)
        operation_id = uuid.uuid4().hex[:12]

        # سجل النوايا: تُكتب الدفعة قبل بدء النقل حتى لا تضيع لو انقطع التطبيق
        self.history_store.begin_intent(
            operation_id, folder,
            os.path.join(folder, OUTPUT_DIR_NAME), total_files,
        )
        self._set_busy(True)
        self.log_message(f"بدء عملية النقل — {total_files} ملف…")

        def job(progress, cancel):
            return move_groups(
                selected, folder, operation_id,
                progress=lambda d, t: progress(
                    d * 100 // max(t, 1), f"جاري النقل… ({d}/{t})"
                ),
                cancel=cancel,
            )

        self._spawn(job, self.on_move_finished)

    def on_move_finished(self, result: dict):
        self.history_store.complete(result["operation_id"], result)
        message = (
            f"تم نقل {result['moved_count']} ملف بنجاح إلى:\n{result['dest_folder']}"
        )
        if result["error_files"]:
            message += f"\n\nتعذر نقل {len(result['error_files'])} ملف"
        QMessageBox.information(self, "نتيجة العملية", message)
        QApplication.beep()
        self.log_message(f"اكتمل النقل — {result['moved_count']} ملف", "SUCCESS")
        # تحديث النتائج محلياً بدل إعادة البحث الكامل
        self._remove_paths_from_results(
            {op["source"] for op in result["operations"]}
        )
        self._set_busy(False)

    # ── سلة المحذوفات ────────────────────────────────────────────────────
    def move_to_trash(self):
        if not TRASH_AVAILABLE:
            QMessageBox.critical(
                self, "غير متوفر",
                "مكتبة send2trash غير مثبتة.\nنفّذ: pip install send2trash",
            )
            return
        selected, fully_selected = self.get_selected()
        if not selected:
            return

        dlg = DryRunDialog(
            selected, "إرسال إلى سلة المحذوفات",
            fully_selected_groups=fully_selected,
            content_warning=self._content_warning(),
            destructive=True,
            dark_mode=self.dark_mode,
            parent=self,
        )
        dlg.exec_()
        if not dlg.confirmed:
            self.log_message("تم إلغاء عملية الحذف من نافذة المعاينة")
            return

        total_files = sum(len(g) for g in selected)
        self._set_busy(True)
        self.log_message(f"بدء إرسال {total_files} ملف إلى سلة المحذوفات…")

        def job(progress, cancel):
            return trash_groups(
                selected,
                progress=lambda d, t: progress(
                    d * 100 // max(t, 1), f"إرسال إلى السلة… ({d}/{t})"
                ),
                cancel=cancel,
            )

        self._spawn(job, self.on_trash_finished)

    def on_trash_finished(self, result: dict):
        count = result["trashed_count"]
        self.log_message(
            f"تم إرسال {count} ملف إلى السلة "
            f"(حجم إجمالي: {format_bytes(result['total_size'])})",
            "SUCCESS",
        )
        if result["failed"]:
            self.log_message(f"فشل في {len(result['failed'])} ملف", "WARNING")
        QMessageBox.information(
            self, "اكتملت العملية",
            f"تم إرسال {count} ملف إلى سلة المحذوفات.\n"
            f"يمكنك استرداد الملفات من سلة محذوفات النظام.",
        )
        self._remove_paths_from_results(set(result["trashed_paths"]))
        self._set_busy(False)

    def _remove_paths_from_results(self, removed: set):
        """إزالة الملفات المنقولة/المحذوفة من النتائج دون إعادة بحث كامل.
        المجموعات التي بقي فيها ملف واحد لم تعد مجموعات تكرار فتُحذف."""
        new_groups = []
        for group in self.similar_groups:
            remaining = [f for f in group if f["path"] not in removed]
            if len(remaining) > 1:
                new_groups.append(remaining)
        self.similar_groups = new_groups
        self._clear_preview()
        self.display_results(new_groups)

    # ── الاسترجاع ────────────────────────────────────────────────────────
    def show_history_dialog(self):
        if not self.history_store.batches:
            QMessageBox.information(
                self, "السجل فارغ",
                "لا توجد عمليات سابقة.\nستُسجَّل هنا كل عملية عزل لتتمكن من إرجاعها.",
            )
            return
        dialog = HistoryDialog(
            self.history_store.batches, dark_mode=self.dark_mode, parent=self
        )
        dialog.restore_requested.connect(self.restore_files)
        dialog.exec_()

    def restore_files(self, batch: dict):
        reply = QMessageBox.question(
            self, "تأكيد الإرجاع",
            f"هل تريد إرجاع {len(batch.get('operations', []))} ملف إلى مواقعها الأصلية؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.log_message(f"بدء إرجاع الملفات — {len(batch.get('operations', []))} ملف…")

        def job(progress, cancel):
            return restore_batch(
                batch,
                progress=lambda d, t: progress(
                    d * 100 // max(t, 1), f"جاري الإرجاع… ({d}/{t})"
                ),
                cancel=cancel,
            )

        self._spawn(job, self.on_restore_finished)

    def on_restore_finished(self, result: dict):
        self.history_store.mark_restore_result(
            result["operation_id"], result["failed_ops"]
        )
        message = f"تم إرجاع {result['restored_count']} ملف بنجاح"
        if result["failed_ops"]:
            message += (
                f"\n\nتعذر إرجاع {len(result['failed_ops'])} ملف — "
                f"تبقى العملية في السجل لإعادة المحاولة على المتبقي"
            )
        QMessageBox.information(self, "نتيجة الإرجاع", message)
        QApplication.beep()
        self.log_message(f"اكتمل الإرجاع — {result['restored_count']} ملف", "SUCCESS")
        self._set_busy(False)
        if self.folder_input.text():
            self.status_bar.showMessage(
                "أعد البحث لتحديث النتائج بعد الإرجاع", 6000
            )

    # ── التصدير والمساعدة ────────────────────────────────────────────────
    def export_report(self):
        if not self.similar_groups:
            QMessageBox.warning(self, "لا نتائج", "لا توجد نتائج للتصدير")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "حفظ التقرير",
            f"duplicate_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "Text Files (*.txt);;CSV Files (*.csv);;JSON Files (*.json)",
        )
        if not file_path:
            return
        # محرك موحّد لاختيار الصيغة بالامتداد (نفس منطق الـ CLI: .csv / .json / .txt)
        from ..core.reports import write_report
        try:
            write_report(self.similar_groups, file_path)
            self.status_bar.showMessage(f"تم حفظ التقرير: {file_path}", 6000)
            self.log_message(f"تم تصدير التقرير: {file_path}", "SUCCESS")
        except OSError as e:
            QMessageBox.critical(self, "خطأ", f"فشل حفظ التقرير:\n{e}")

    def show_guide(self):
        GuideDialog(dark_mode=self.dark_mode, parent=self).exec_()

    def show_about(self):
        AboutDialog(
            icon=load_app_icon(), dark_mode=self.dark_mode, parent=self
        ).exec_()

    # ── الإعدادات والإغلاق ───────────────────────────────────────────────
    def load_settings(self):
        self.threshold_spin.setValue(self.settings.value("threshold", 0.0, type=float))
        self.same_ext_check.setChecked(self.settings.value("same_ext", False, type=bool))
        self.recursive_check.setChecked(
            self.settings.value("recursive", False, type=bool)
        )
        mode = self.settings.value("detect_mode", MODE_PARTIAL)
        index = self.detect_mode_combo.findData(mode)
        if index >= 0:
            self.detect_mode_combo.setCurrentIndex(index)
        last_folder = self.settings.value("last_folder", "")
        if last_folder and os.path.isdir(last_folder):
            self.folder_input.setText(last_folder)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter_state = self.settings.value("splitter")
        if splitter_state is not None:
            self.splitter.restoreState(splitter_state)
        show_preview = self.settings.value("show_preview", True, type=bool)
        self.act_preview.setChecked(show_preview)
        self.preview_card.setVisible(show_preview)
        self._update_mode_hint()

    def save_settings(self):
        self.settings.setValue("threshold", self.threshold_spin.value())
        self.settings.setValue("same_ext", self.same_ext_check.isChecked())
        self.settings.setValue("recursive", self.recursive_check.isChecked())
        self.settings.setValue("detect_mode", self.detect_mode_combo.currentData())
        self.settings.setValue("last_folder", self.folder_input.text())
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        self.settings.setValue("show_preview", self.act_preview.isChecked())

    def closeEvent(self, event):
        # إيقاف كل الخيوط الحية (القائمة تشمل أي عامل أُنشئ عبر _spawn)
        for worker in list(self._workers):
            if worker.isRunning():
                worker.stop()
                worker.wait(3000)
        self.save_settings()
        event.accept()


def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    # Fusion أساس محايد يحترم QPalette على كل المنصّات، فيبدو الوضع الداكن
    # صحيحاً بلا مفاجآت من ثيم النظام.
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(load_app_icon())
    if sys.platform.startswith("win"):
        app.setFont(QFont("Segoe UI", 10))
    app.setLayoutDirection(Qt.RightToLeft)

    window = FileSizeDuplicateFinder()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
