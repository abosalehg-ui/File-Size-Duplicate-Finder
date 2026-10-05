"""النافذة الرئيسية للتطبيق.

تنظيم الواجهة في ثلاث مناطق واضحة تتبع تدفّق العمل:

1. **بطاقة البحث** (أعلى) — أين نبحث وكيف، ومعها الإجراء الأساسي الوحيد.
2. **النتائج** (الوسط) — إحصاءات، فلترة، شجرة المجموعات، ولوحة معاينة جانبية.
3. **شريط الإجراءات** (أسفل) — ما يُفعل بالتحديد، ويظل معطّلاً حتى يوجد تحديد فعلي.

القوائم وشريط الأدوات يحملان الإجراءات العامة (الثيم، السجل، الإرجاع،
التصدير) فلا تتزاحم مع مسار العمل الأساسي.

هذه الوحدة تبني هيكل النافذة وتدير الثيم والإعدادات فقط؛ منطق النتائج
والتحديد في `results_view.py`، وتشغيل العمليات الطويلة في `controllers.py`.
"""

from __future__ import annotations

import html
import os
import sys
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QSettings, QSize, Qt
from PyQt5.QtGui import QFont, QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QDockWidget,
    QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QSplitter, QStatusBar,
    QToolBar, QTextEdit, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..core.fileinfo import FileInfo
from ..core.hashing import MODE_FULL, MODE_PARTIAL, MODE_SIZE
from ..ops.history import HistoryStore
from ..ops.operations import TRASH_AVAILABLE
from . import icons, theme
from .controllers import OperationsMixin
from .dialogs import AboutDialog, GuideDialog
from .results_view import ResultsViewMixin
from .widgets import Card, apply_variant
from .workers import Worker

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


class FileSizeDuplicateFinder(ResultsViewMixin, OperationsMixin, QMainWindow):
    """النافذة الرئيسية."""

    def __init__(self):
        super().__init__()
        self.similar_groups: list[list[FileInfo]] = []
        self._workers: list[Worker] = []
        self._updating_checks = False
        self._busy = False
        self._scan_root = ""
        self._current_preview: FileInfo | None = None
        self._init_selection_tracking()
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
        # عرض أدنى صريح فقط. الطول الأدنى يُحسبه Qt من التخطيط نفسه: لو
        # فُرض طول أصغر من حاجة التخطيط الحقيقية اقتطع Qt المحتوى فرُسمت
        # العناصر فوق بعضها (كان يحدث عند فتح لوحة السجل).
        self.setMinimumWidth(960)
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
        self.act_clear_cache = self._act(
            "مسح كاش البصمات…", "hash", self.clear_hash_cache, "",
            "حذف البصمات المخزنة (ومعها مسارات الملفات) — البحث التالي يعيد حسابها",
        )
        self.act_clear_history = self._act(
            "مسح سجل العمليات…", "x", self.clear_history, "",
            "حذف سجل العمليات ونسخه الاحتياطية — لا يمس الملفات نفسها",
            role="danger",
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

        data_menu = bar.addMenu("البيانات")
        data_menu.addAction(self.act_clear_cache)
        data_menu.addAction(self.act_clear_history)

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

    # ── مساعدات ربط الأزرار بالإجراءات ─────────────────────────────────
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
        # حدّ أدنى صغير: اللوحة لا ترفع الطول الأدنى للنافذة أكثر من اللازم
        self.log_text.setMinimumHeight(56)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            theme.SPACE_MD, theme.SPACE_SM, theme.SPACE_MD, theme.SPACE_SM
        )
        layout.setSpacing(theme.SPACE_XS)
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
        dock.hide()
        dock.visibilityChanged.connect(self._on_log_visibility)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.log_dock = dock

    def _toggle_log_dock(self, visible: bool):
        self.log_dock.setVisible(visible)
        if visible:
            # ارتفاع ابتدائي معقول: لولاه أخذت اللوحة حجمها المقترح الكبير
            # فتقلّصت شجرة النتائج إلى سطر واحد
            self.resizeDocks([self.log_dock], [190], Qt.Vertical)

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
            f'<span style="color: {p.code_text};">{html.escape(message)}</span><br>'
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
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.log_text.toPlainText())
        except OSError as e:
            QMessageBox.critical(self, "تعذّر حفظ السجل", f"فشل حفظ السجل:\n{e}")
            return
        self.log_message(f"تم حفظ السجل: {file_path}", "SUCCESS")

    # ── حالة الانشغال ────────────────────────────────────────────────────
    def _set_busy(self, busy: bool):
        self._busy = busy
        self.act_search.setEnabled(not busy)
        self.act_stop.setEnabled(busy)
        self.act_browse.setEnabled(not busy)
        self.act_restore.setEnabled(not busy)
        self.act_clear_cache.setEnabled(not busy)
        self.act_clear_history.setEnabled(not busy)
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

    # ── المساعدة ─────────────────────────────────────────────────────────
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
        # إيقاف كل الخيوط الحية (القائمة تشمل أي عامل أُنشئ عبر _spawn).
        # الانتظار بلا مهلة مقصود: الإلغاء تعاوني ويُفحص عند كل ملف/مقطع، أما
        # هدم QThread وهو يعمل فيُسقط التطبيق في منتصف نقل ملف. ما نُقل قبل
        # الإيقاف مسجّل في اليومية ويُستعاد عند التشغيل التالي.
        for worker in list(self._workers):
            if worker.isRunning():
                worker.stop()
                worker.wait()
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
