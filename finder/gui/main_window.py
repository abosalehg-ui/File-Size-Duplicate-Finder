"""النافذة الرئيسية للتطبيق."""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl, QSettings
from PyQt5.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap,
)
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QShortcut,
    QSplitter, QStatusBar, QTabWidget, QTextEdit, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, COPYRIGHT, DEVELOPER, EMAIL, __version__
from ..core import (
    DEFAULT_EXCLUDE_DIRS, HashCache, format_bytes, group_by_size, scan_folder,
)
from ..core.hashing import MODE_FULL, MODE_PARTIAL, MODE_SIZE, refine_groups_by_hash
from ..ops.history import HistoryStore
from ..ops.operations import (
    OUTPUT_DIR_NAME, TRASH_AVAILABLE, move_groups, restore_batch, trash_groups,
)
from .dialogs import DryRunDialog, HistoryDialog
from .selection import (
    STATE_CHECKED, STATE_PARTIAL, group_tristate, partition_keep_one,
)
from .styles import DARK_QSS, LIGHT_QSS, group_palette
from .workers import Worker

# عدد المجموعات الذي نتوقف بعده عن التوسيع التلقائي حفاظاً على استجابة الشجرة
AUTO_EXPAND_GROUP_LIMIT = 100

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg"}


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


class FileSizeDuplicateFinder(QMainWindow):
    """النافذة الرئيسية."""

    def __init__(self):
        super().__init__()
        self.similar_groups: list[list[dict]] = []
        self._workers: list[Worker] = []
        self._updating_checks = False
        self.settings = QSettings("FileSizeDuplicateFinder", "Settings")
        self.dark_mode = self.settings.value("dark_mode", False, type=bool)
        self.history_store = HistoryStore()

        self.setAcceptDrops(True)
        self.init_ui()
        self.load_settings()

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
                    self.log_message(f"📂 تم تعيين المجلد عبر السحب: {path}")
                    event.acceptProposedAction()
                    return
        event.ignore()

    # ── بناء الواجهة ─────────────────────────────────────────────────────
    def init_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.setWindowIcon(load_app_icon())
        self.setMinimumSize(1000, 750)
        self.setLayoutDirection(Qt.RightToLeft)
        self.apply_style()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        main_layout.addWidget(self._create_title_frame())

        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self._create_search_tab(), "🔍 البحث والعزل")
        self.tab_widget.addTab(self._create_log_tab(), "📋 سجل العمليات")
        main_layout.addWidget(self.tab_widget)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("جاهز للعمل")

        # اختصار تركيز حقل الفلترة (Ctrl+F)
        filter_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        filter_shortcut.activated.connect(self._focus_filter)

        copyright_label = QLabel(f"تطوير: {DEVELOPER} | {EMAIL} | {COPYRIGHT}")
        copyright_label.setAlignment(Qt.AlignCenter)
        copyright_label.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        main_layout.addWidget(copyright_label)

    def apply_style(self):
        self.setStyleSheet(DARK_QSS if self.dark_mode else LIGHT_QSS)

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self.settings.setValue("dark_mode", self.dark_mode)
        self.apply_style()
        self.dark_mode_btn.setText(
            "☀️ الوضع الفاتح" if self.dark_mode else "🌙 الوضع الداكن"
        )
        self._apply_group_colors()
        self.log_message("تم تبديل وضع العرض")

    def _create_title_frame(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                border-radius: 10px; padding: 15px;
            }
        """)
        outer = QHBoxLayout(frame)

        text_col = QVBoxLayout()
        title = QLabel(f"🔍 {APP_NAME}")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        text_col.addWidget(title)
        subtitle = QLabel("ابحث عن الملفات المكررة أو المتقاربة بالحجم وقم بعزلها بأمان")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        text_col.addWidget(subtitle)
        outer.addLayout(text_col, 1)

        self.dark_mode_btn = QToolButton()
        self.dark_mode_btn.setText(
            "☀️ الوضع الفاتح" if self.dark_mode else "🌙 الوضع الداكن"
        )
        self.dark_mode_btn.setStyleSheet(
            "QToolButton { background-color: rgba(255,255,255,0.18); color: white; "
            "padding: 8px 14px; border-radius: 6px; font-weight: bold; }"
            "QToolButton:hover { background-color: rgba(255,255,255,0.3); }"
        )
        self.dark_mode_btn.clicked.connect(self.toggle_dark_mode)
        outer.addWidget(self.dark_mode_btn, 0, Qt.AlignTop)
        return frame

    def _create_search_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # إعدادات البحث
        settings_group = QGroupBox("إعدادات البحث")
        settings_layout = QVBoxLayout(settings_group)

        folder_layout = QHBoxLayout()
        folder_label = QLabel("📁 المجلد:")
        folder_label.setMinimumWidth(80)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("اختر المجلد للبحث فيه أو اسحبه إلى النافذة...")
        self.folder_input.setReadOnly(True)
        self.folder_input.setAccessibleName("مسار مجلد البحث")
        browse_btn = QPushButton("استعراض 📂")
        browse_btn.setShortcut(QKeySequence("Ctrl+O"))
        browse_btn.setAccessibleName("استعراض واختيار مجلد")
        browse_btn.setToolTip("اختيار مجلد البحث (Ctrl+O)")
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_input, 1)
        folder_layout.addWidget(browse_btn)
        settings_layout.addLayout(folder_layout)

        options_layout = QHBoxLayout()
        options_layout.addWidget(QLabel("📏 حد التقارب (ميجابايت):"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1000)   # 0 = تطابق حجم دقيق
        self.threshold_spin.setValue(0.0)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setToolTip("0 = تطابق حجم دقيق (مُستحسن مع أوضاع الـ hash)")
        options_layout.addWidget(self.threshold_spin)

        options_layout.addSpacing(20)
        self.same_ext_check = QCheckBox("🏷️ نفس الامتداد فقط")
        options_layout.addWidget(self.same_ext_check)

        options_layout.addSpacing(10)
        self.recursive_check = QCheckBox("🌳 المجلدات الفرعية")
        self.recursive_check.setToolTip(
            "البحث المتداخل في كل المجلدات الفرعية "
            "(يتجاهل المجلدات النظامية مثل .git و node_modules)"
        )
        options_layout.addWidget(self.recursive_check)

        options_layout.addSpacing(10)
        options_layout.addWidget(QLabel("🔍 وضع الكشف:"))
        self.detect_mode_combo = QComboBox()
        self.detect_mode_combo.addItem("حجم متقارب (سريع)", MODE_SIZE)
        self.detect_mode_combo.addItem("Partial hash (متوازن)", MODE_PARTIAL)
        self.detect_mode_combo.addItem("تكرار حقيقي SHA-256 (دقيق)", MODE_FULL)
        self.detect_mode_combo.setCurrentIndex(1)
        self.detect_mode_combo.setToolTip(
            "حجم متقارب: مقارنة الأحجام فقط — لا يضمن تطابق المحتوى.\n"
            "Partial hash: نفس الحجم + توقيع من بداية ونهاية الملف.\n"
            "تكرار حقيقي: SHA-256 كامل — أبطأ لكن مضمون."
        )
        options_layout.addWidget(self.detect_mode_combo)
        options_layout.addStretch()
        settings_layout.addLayout(options_layout)
        layout.addWidget(settings_group)

        layout.addLayout(self._create_control_row())

        # شريط التقدم
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(25)
        self.progress_label = QLabel("")
        self.progress_label.setMinimumWidth(200)
        progress_layout.addWidget(self.progress_bar, 1)
        progress_layout.addWidget(self.progress_label)
        layout.addLayout(progress_layout)

        # النتائج والمعاينة
        splitter = QSplitter(Qt.Vertical)
        results_group = QGroupBox("النتائج")
        results_layout = QVBoxLayout(results_group)

        self.stats_label = QLabel("📊 لم يتم البحث بعد")
        # الألوان في styles.py (objectName) لتتبع الوضع الفاتح/الداكن
        self.stats_label.setObjectName("statsBox")
        results_layout.addWidget(self.stats_label)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("🔎 فلترة:"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(
            "اكتب جزءاً من اسم الملف أو الامتداد لتصفية المجموعات فوراً... (Ctrl+F)"
        )
        self.filter_input.setAccessibleName("فلترة النتائج")
        self.filter_input.textChanged.connect(self.apply_results_filter)
        filter_row.addWidget(self.filter_input, 1)
        clear_filter_btn = QToolButton()
        clear_filter_btn.setText("✕")
        clear_filter_btn.setToolTip("مسح الفلتر")
        clear_filter_btn.clicked.connect(self.filter_input.clear)
        filter_row.addWidget(clear_filter_btn)
        results_layout.addLayout(filter_row)

        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels(["", "المجموعة", "اسم الملف", "الحجم", "الامتداد"])
        self.results_tree.setAccessibleName("نتائج مجموعات الملفات المتقاربة")
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.itemChanged.connect(self.on_item_check_changed)
        self.results_tree.itemClicked.connect(self.on_item_clicked)
        self.results_tree.itemDoubleClicked.connect(self.open_file_location)
        self.results_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_tree.customContextMenuRequested.connect(self.show_context_menu)
        header = self.results_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.results_tree.setColumnWidth(0, 40)
        results_layout.addWidget(self.results_tree)

        results_layout.addLayout(self._create_select_row())
        splitter.addWidget(results_group)

        # معاينة الملف
        preview_group = QGroupBox("معاينة الملف")
        preview_layout = QHBoxLayout(preview_group)
        self.preview_thumb = QLabel()
        self.preview_thumb.setFixedSize(140, 140)
        self.preview_thumb.setAlignment(Qt.AlignCenter)
        self.preview_thumb.setStyleSheet(
            "QLabel { border: 1px dashed #999; border-radius: 6px; color: #888; }"
        )
        self.preview_thumb.setText("🖼️\n(معاينة)")
        preview_layout.addWidget(self.preview_thumb)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(140)
        self.preview_text.setPlaceholderText("اضغط على ملف لعرض تفاصيله...")
        preview_layout.addWidget(self.preview_text, 1)
        splitter.addWidget(preview_group)
        splitter.setSizes([500, 160])
        layout.addWidget(splitter, 1)
        return widget

    def _create_control_row(self) -> QHBoxLayout:
        """صف أزرار التحكم (بحث/إيقاف/عزل/سلة/إرجاع)."""
        control_layout = QHBoxLayout()
        self.search_btn = QPushButton("🔍 بدء البحث")
        self.search_btn.setMinimumHeight(45)
        self.search_btn.setShortcut(QKeySequence("F5"))
        self.search_btn.setAccessibleName("بدء البحث")
        self.search_btn.setToolTip("بدء البحث عن الملفات المتقاربة (F5)")
        self.search_btn.clicked.connect(self.start_search)
        self.stop_btn = QPushButton("⏹ إيقاف")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setAccessibleName("إيقاف العملية الجارية")
        self.stop_btn.clicked.connect(self.stop_current_worker)
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #e74c3c; }"
            "QPushButton:hover { background-color: #c0392b; }"
            "QPushButton:disabled { background-color: #bdc3c7; }"
        )
        self.move_btn = QPushButton("📦 عزل المحدد")
        self.move_btn.setEnabled(False)
        self.move_btn.setAccessibleName("عزل الملفات المحددة إلى مجلدات")
        self.move_btn.clicked.connect(self.move_files)
        self.move_btn.setStyleSheet(
            "QPushButton { background-color: #27ae60; }"
            "QPushButton:hover { background-color: #1e8449; }"
            "QPushButton:disabled { background-color: #bdc3c7; }"
        )
        self.trash_btn = QPushButton("🗑️ سلة المحذوفات")
        self.trash_btn.setEnabled(False)
        self.trash_btn.setAccessibleName("إرسال المحدد إلى سلة المحذوفات")
        self.trash_btn.clicked.connect(self.move_to_trash)
        self.trash_btn.setToolTip(
            "إرسال الملفات المحددة إلى سلة محذوفات النظام (قابلة للاسترداد)"
            if TRASH_AVAILABLE else "غير متوفر — ثبّت send2trash"
        )
        self.trash_btn.setStyleSheet(
            "QPushButton { background-color: #c0392b; }"
            "QPushButton:hover { background-color: #962d22; }"
            "QPushButton:disabled { background-color: #bdc3c7; }"
        )
        self.restore_btn = QPushButton("🔄 إرجاع الملفات")
        self.restore_btn.setAccessibleName("فتح سجل العمليات لإرجاع الملفات")
        self.restore_btn.clicked.connect(self.show_history_dialog)
        self.restore_btn.setStyleSheet(
            "QPushButton { background-color: #f39c12; }"
            "QPushButton:hover { background-color: #d68910; }"
        )
        control_layout.addWidget(self.search_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.move_btn)
        control_layout.addWidget(self.trash_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.restore_btn)
        return control_layout

    def _create_select_row(self) -> QHBoxLayout:
        """صف أزرار التحديد — يشمل التحديد الذكي (إبقاء نسخة) والتصدير."""
        select_layout = QHBoxLayout()
        select_all_btn = QPushButton("☑ تحديد الكل")
        select_all_btn.clicked.connect(self.select_all)
        select_all_btn.setStyleSheet("background-color: #9b59b6;")
        deselect_all_btn = QPushButton("☐ إلغاء التحديد")
        deselect_all_btn.clicked.connect(self.deselect_all)
        deselect_all_btn.setStyleSheet("background-color: #95a5a6;")
        keep_newest_btn = QPushButton("🧠 الكل عدا الأحدث")
        keep_newest_btn.setToolTip("تحديد كل ملفات كل مجموعة ما عدا الأحدث تعديلاً (تبقى نسخة)")
        keep_newest_btn.clicked.connect(lambda: self.smart_select(keep="newest"))
        keep_newest_btn.setStyleSheet("background-color: #8e44ad;")
        keep_oldest_btn = QPushButton("🧠 الكل عدا الأقدم")
        keep_oldest_btn.setToolTip("تحديد كل ملفات كل مجموعة ما عدا الأقدم تعديلاً (تبقى نسخة)")
        keep_oldest_btn.clicked.connect(lambda: self.smart_select(keep="oldest"))
        keep_oldest_btn.setStyleSheet("background-color: #8e44ad;")
        export_btn = QPushButton("💾 تصدير التقرير")
        export_btn.setShortcut(QKeySequence("Ctrl+S"))
        export_btn.setAccessibleName("تصدير تقرير النتائج")
        export_btn.setToolTip("تصدير النتائج إلى ملف (Ctrl+S)")
        export_btn.clicked.connect(self.export_report)
        export_btn.setStyleSheet("background-color: #1abc9c;")
        select_layout.addWidget(select_all_btn)
        select_layout.addWidget(deselect_all_btn)
        select_layout.addWidget(keep_newest_btn)
        select_layout.addWidget(keep_oldest_btn)
        select_layout.addStretch()
        select_layout.addWidget(export_btn)
        return select_layout

    def _create_log_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', 'Courier New', monospace; "
            "font-size: 11px; background-color: #1e1e1e; color: #d4d4d4; "
            "border-radius: 5px; }"
        )
        layout.addWidget(self.log_text)
        log_buttons = QHBoxLayout()
        clear_log_btn = QPushButton("🗑 مسح السجل")
        clear_log_btn.clicked.connect(self.log_text.clear)
        clear_log_btn.setStyleSheet("background-color: #e74c3c;")
        save_log_btn = QPushButton("💾 حفظ السجل")
        save_log_btn.clicked.connect(self.save_log)
        save_log_btn.setStyleSheet("background-color: #27ae60;")
        log_buttons.addStretch()
        log_buttons.addWidget(save_log_btn)
        log_buttons.addWidget(clear_log_btn)
        layout.addLayout(log_buttons)
        return widget

    # ── السجل النصي ──────────────────────────────────────────────────────
    def log_message(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "#58a6ff", "SUCCESS": "#3fb950",
            "WARNING": "#d29922", "ERROR": "#f85149",
        }
        color = colors.get(level, "#d4d4d4")
        self.log_text.insertHtml(
            f'<span style="color: #888;">[{timestamp}]</span> '
            f'<span style="color: {color};">[{level}]</span> '
            f'<span style="color: #d4d4d4;">{message}</span><br>'
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
        for worker in self._workers:
            if worker.isRunning():
                worker.stop()
        self.progress_label.setText("جاري الإيقاف...")

    def _on_generic_error(self, error: str):
        QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء العملية:\n{error}")
        self.log_message(f"خطأ: {error}", "ERROR")
        self._set_busy(False)

    def _set_busy(self, busy: bool):
        self.search_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        has_groups = bool(self.similar_groups)
        self.move_btn.setEnabled(not busy and has_groups)
        self.trash_btn.setEnabled(not busy and has_groups and TRASH_AVAILABLE)
        self.restore_btn.setEnabled(not busy)

    def on_progress(self, value: int, message: str):
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)
        self.status_bar.showMessage(message)

    # ── البحث ────────────────────────────────────────────────────────────
    def browse_folder(self):
        last_folder = self.settings.value("last_folder", "")
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
                "⚠️ <b>وضع الكشف الحالي يقارن الأحجام فقط</b> — تقارب الحجم لا يعني "
                "تطابق المحتوى. للتأكد من التكرار الفعلي استخدم وضع Partial أو SHA-256."
            )
        if mode == MODE_PARTIAL:
            return (
                "⚠️ <b>وضع Partial يقارن بداية ونهاية الملف فقط</b> — قد تظهر ملفات "
                "كبيرة تختلف في وسطها كأنها متطابقة. للتأكد التام استخدم وضع SHA-256."
            )
        return ""

    def start_search(self):
        folder = self.folder_input.text()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "تنبيه", "الرجاء اختيار مجلد صالح")
            return

        self.results_tree.clear()
        self.similar_groups = []
        self.progress_bar.setValue(0)
        self._set_busy(True)
        self.log_message("بدء البحث عن الملفات المتقاربة...")

        threshold_bytes = int(self.threshold_spin.value() * 1024 * 1024)
        same_ext = self.same_ext_check.isChecked()
        recursive = self.recursive_check.isChecked()
        mode = self.detect_mode_combo.currentData() or MODE_SIZE

        def job(progress, cancel):
            def scan_progress(n):
                progress(min(45, 5 + n // 500), f"جاري فحص الملفات... ({n} ملف)")

            files = scan_folder(
                folder, recursive=recursive, exclude_dirs=DEFAULT_EXCLUDE_DIRS,
                cancel=cancel, progress=scan_progress,
            )
            progress(48, f"تحليل {len(files)} ملف بخوارزمية النافذة المنزلقة...")
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
                        progress(pct, f"حساب {label}... ({done}/{total})")

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
        self.progress_label.setText(f"اكتمل البحث — {len(groups)} مجموعة")
        QApplication.beep()
        self.log_message(f"اكتمل البحث - تم العثور على {len(groups)} مجموعة", "SUCCESS")

    def on_search_cancelled(self):
        self._set_busy(False)
        self.progress_label.setText("تم إيقاف البحث")
        self.log_message("تم إيقاف البحث", "WARNING")

    # ── عرض النتائج والتحديد ─────────────────────────────────────────────
    def display_results(self, groups: list):
        self.results_tree.blockSignals(True)
        self.results_tree.setUpdatesEnabled(False)
        try:
            self.results_tree.clear()
            total_files = 0
            total_size = 0
            potential_savings = 0
            expand = len(groups) <= AUTO_EXPAND_GROUP_LIMIT

            for group_idx, group_files in enumerate(groups):
                group_item = QTreeWidgetItem(self.results_tree)
                group_item.setFlags(group_item.flags() | Qt.ItemIsUserCheckable)
                group_item.setCheckState(0, Qt.Unchecked)
                group_item.setText(1, f"المجموعة {group_idx + 1}")
                group_size = sum(f["size"] for f in group_files)
                group_item.setText(
                    3, f"{len(group_files)} ملفات - {format_bytes(group_size)}"
                )
                group_item.setExpanded(expand)

                sorted_files = sorted(group_files, key=lambda x: x["size"], reverse=True)
                potential_savings += sum(f["size"] for f in sorted_files[1:])

                for file_info in group_files:
                    file_item = QTreeWidgetItem(group_item)
                    file_item.setFlags(file_item.flags() | Qt.ItemIsUserCheckable)
                    file_item.setCheckState(0, Qt.Unchecked)
                    file_item.setText(2, file_info["name"])
                    file_item.setText(3, format_bytes(file_info["size"]))
                    file_item.setText(4, file_info["ext"] or "بدون")
                    file_item.setData(0, Qt.UserRole, file_info)
                    total_files += 1
                    total_size += file_info["size"]

            self.stats_label.setText(
                f"📊 الإحصائيات: {len(groups)} مجموعة | {total_files} ملف | "
                f"الحجم الكلي: {format_bytes(total_size)} | "
                f"💰 التوفير المحتمل: {format_bytes(potential_savings)}"
            )
        finally:
            self.results_tree.setUpdatesEnabled(True)
            self.results_tree.blockSignals(False)
        self._apply_group_colors()
        if self.filter_input.text():
            self.apply_results_filter(self.filter_input.text())

    def _apply_group_colors(self):
        colors, text_color = group_palette(self.dark_mode)
        fg = QColor(text_color)
        root = self.results_tree.invisibleRootItem()
        for i in range(root.childCount()):
            bg = QColor(colors[i % len(colors)])
            group_item = root.child(i)
            for col in range(5):
                group_item.setBackground(col, bg)
                group_item.setForeground(col, fg)

    def _focus_filter(self):
        self.tab_widget.setCurrentIndex(0)
        self.filter_input.setFocus()
        self.filter_input.selectAll()

    def apply_results_filter(self, text: str):
        text = (text or "").strip().lower()
        root = self.results_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_item = root.child(i)
            any_visible = False
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if not text:
                    child.setHidden(False)
                    any_visible = True
                else:
                    match = (text in child.text(2).lower()
                             or text in child.text(4).lower())
                    child.setHidden(not match)
                    any_visible = any_visible or match
            group_item.setHidden(bool(text) and not any_visible)

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

    def select_all(self):
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
        self.log_message(f"تحديد ذكي: كل الملفات عدا {label} في كل مجموعة")

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

    # ── المعاينة والقوائم ────────────────────────────────────────────────
    def on_item_clicked(self, item: QTreeWidgetItem, column: int):
        info = item.data(0, Qt.UserRole)
        if not info:
            return
        created, modified = _file_times(info["path"])
        lines = [
            f"📄 اسم الملف: {info['name']}",
            f"📏 الحجم: {format_bytes(info['size'])}",
            f"🏷️ الامتداد: {info['ext'] or 'بدون'}",
        ]
        if created:
            lines.append(f"📅 تاريخ الإنشاء: {created}")
        if modified:
            lines.append(f"📝 آخر تعديل: {modified}")
        lines.append(f"📁 المسار: {info['path']}")
        self.preview_text.setText("\n".join(lines))
        self._update_thumbnail(info["path"], info.get("ext", ""))

    def _update_thumbnail(self, path: str, ext: str):
        if ext.lower() in IMAGE_EXTS and os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self.preview_thumb.setPixmap(pix.scaled(
                    self.preview_thumb.width() - 4,
                    self.preview_thumb.height() - 4,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                ))
                return
        label = ext.upper().lstrip(".") if ext else "FILE"
        self.preview_thumb.setPixmap(QPixmap())
        self.preview_thumb.setText(f"📄\n{label}")

    def open_file_location(self, item: QTreeWidgetItem, column: int):
        info = item.data(0, Qt.UserRole)
        if info:
            folder = os.path.dirname(info["path"])
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self.log_message(f"فتح المجلد: {folder}")

    def show_context_menu(self, position):
        item = self.results_tree.itemAt(position)
        if not item or not item.data(0, Qt.UserRole):
            return
        menu = QMenu(self)
        open_action = QAction("📂 فتح موقع الملف", self)
        open_action.triggered.connect(lambda: self.open_file_location(item, 0))
        menu.addAction(open_action)
        select_action = QAction("☑ تحديد", self)
        select_action.triggered.connect(lambda: item.setCheckState(0, Qt.Checked))
        menu.addAction(select_action)
        menu.exec_(self.results_tree.viewport().mapToGlobal(position))

    # ── النقل ────────────────────────────────────────────────────────────
    def move_files(self):
        selected, fully_selected = self.get_selected()
        if not selected:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد الملفات المراد عزلها")
            return

        dlg = DryRunDialog(
            selected, "عزل إلى مجلدات",
            fully_selected_groups=fully_selected,
            content_warning=self._content_warning(),
            parent=self,
        )
        dlg.exec_()
        if not dlg.confirmed:
            self.log_message("تم إلغاء العملية من نافذة المعاينة")
            return

        folder = self.folder_input.text()
        total_files = sum(len(g) for g in selected)
        operation_id = uuid.uuid4().hex[:12]

        # سجل النوايا: تُكتب الدفعة قبل بدء النقل حتى لا تضيع لو انقطع التطبيق
        self.history_store.begin_intent(
            operation_id, folder,
            os.path.join(folder, OUTPUT_DIR_NAME), total_files,
        )
        self._set_busy(True)
        self.log_message(f"بدء عملية النقل - {total_files} ملف...")

        def job(progress, cancel):
            return move_groups(
                selected, folder, operation_id,
                progress=lambda d, t: progress(
                    d * 100 // max(t, 1), f"جاري النقل... ({d}/{t})"
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
        self.log_message(f"اكتمل النقل - {result['moved_count']} ملف", "SUCCESS")
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
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد الملفات أولاً")
            return

        dlg = DryRunDialog(
            selected, "إرسال إلى سلة المحذوفات",
            fully_selected_groups=fully_selected,
            content_warning=self._content_warning(),
            parent=self,
        )
        dlg.exec_()
        if not dlg.confirmed:
            self.log_message("تم إلغاء عملية الحذف من نافذة المعاينة")
            return

        total_files = sum(len(g) for g in selected)
        self._set_busy(True)
        self.log_message(f"بدء إرسال {total_files} ملف إلى سلة المحذوفات...")

        def job(progress, cancel):
            return trash_groups(
                selected,
                progress=lambda d, t: progress(
                    d * 100 // max(t, 1), f"إرسال إلى السلة... ({d}/{t})"
                ),
                cancel=cancel,
            )

        self._spawn(job, self.on_trash_finished)

    def on_trash_finished(self, result: dict):
        count = result["trashed_count"]
        self.log_message(
            f"✅ تم إرسال {count} ملف إلى السلة "
            f"(حجم إجمالي: {format_bytes(result['total_size'])})",
            "SUCCESS",
        )
        if result["failed"]:
            self.log_message(f"⚠️ فشل في {len(result['failed'])} ملف", "WARNING")
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
        self.display_results(new_groups)

    # ── الاسترجاع ────────────────────────────────────────────────────────
    def show_history_dialog(self):
        if not self.history_store.batches:
            QMessageBox.information(self, "السجل فارغ", "لا توجد عمليات سابقة")
            return
        dialog = HistoryDialog(self.history_store.batches, self)
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
        self.log_message(f"بدء إرجاع الملفات — {len(batch.get('operations', []))} ملف...")

        def job(progress, cancel):
            return restore_batch(
                batch,
                progress=lambda d, t: progress(
                    d * 100 // max(t, 1), f"جاري الإرجاع... ({d}/{t})"
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
        self.log_message(f"اكتمل الإرجاع - {result['restored_count']} ملف", "SUCCESS")
        self._set_busy(False)
        if self.folder_input.text():
            self.log_message("أعد البحث لتحديث النتائج بعد الإرجاع", "INFO")

    # ── التصدير ──────────────────────────────────────────────────────────
    def export_report(self):
        if not self.similar_groups:
            QMessageBox.warning(self, "تنبيه", "لا توجد نتائج للتصدير")
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
            QMessageBox.information(self, "نجاح", f"تم حفظ التقرير:\n{file_path}")
            self.log_message(f"تم تصدير التقرير: {file_path}", "SUCCESS")
        except OSError as e:
            QMessageBox.critical(self, "خطأ", f"فشل حفظ التقرير:\n{e}")

    # ── الإعدادات والإغلاق ───────────────────────────────────────────────
    def load_settings(self):
        self.threshold_spin.setValue(self.settings.value("threshold", 0.0, type=float))
        self.same_ext_check.setChecked(self.settings.value("same_ext", False, type=bool))
        last_folder = self.settings.value("last_folder", "")
        if last_folder and os.path.isdir(last_folder):
            self.folder_input.setText(last_folder)

    def save_settings(self):
        self.settings.setValue("threshold", self.threshold_spin.value())
        self.settings.setValue("same_ext", self.same_ext_check.isChecked())
        self.settings.setValue("last_folder", self.folder_input.text())

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
    app.setWindowIcon(load_app_icon())
    if sys.platform.startswith("win"):
        app.setFont(QFont("Segoe UI", 10))
    app.setLayoutDirection(Qt.RightToLeft)

    window = FileSizeDuplicateFinder()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
