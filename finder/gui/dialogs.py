"""حوارات الواجهة: معاينة العملية، سجل العمليات، الدليل، وحول التطبيق."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import APP_NAME, COPYRIGHT, DEVELOPER, EMAIL, __version__
from ..core.formats import format_bytes
from ..ops.history import STATUS_INTERRUPTED, STATUS_PARTIAL
from . import icons, textfmt, theme
from .widgets import apply_variant

# عتبات تنبيه العمليات الكبيرة
LARGE_OP_FILE_COUNT = 100
LARGE_OP_SIZE_BYTES = 1024 * 1024 * 1024  # 1 GB

_STATUS_LABELS = {
    "completed": "قابل للإرجاع",
    "restored": "تم الإرجاع",
    STATUS_PARTIAL: "إرجاع جزئي — متبقٍ",
    STATUS_INTERRUPTED: "انقطعت — راجعها",
    "in_progress": "جارية",
}

_STATUS_ICONS = {
    "completed": "archive",
    "restored": "check",
    STATUS_PARTIAL: "alert",
    STATUS_INTERRUPTED: "alert",
    "in_progress": "clock",
}


class _BaseDialog(QDialog):
    """أساس مشترك: اتجاه من اليمين، ثيم موروث، وصف عنوان بأيقونة."""

    def __init__(self, title: str, dark_mode: bool = False, parent=None):
        super().__init__(parent)
        self.dark_mode = dark_mode
        self.p = theme.palette(dark_mode)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft)

    def header(self, icon_name: str, title: str, subtitle: str = "") -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_MD)
        badge = QLabel()
        badge.setFixedSize(theme.ICON_LG, theme.ICON_LG)
        badge.setPixmap(icons.pixmap(icon_name, self.p.primary, theme.ICON_LG))
        row.addWidget(badge, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("emptyTitle")
        text_col.addWidget(heading)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            text_col.addWidget(hint)
        row.addLayout(text_col, 1)
        return widget

    def notice(self, html: str, kind: str = "warning") -> QLabel:
        """ملصق تنبيه ملوّن دلالياً — الألوان من الثيم لا مكتوبة يدوياً."""
        label = QLabel(html)
        label.setWordWrap(True)
        label.setObjectName(
            {"warning": "warningBox", "danger": "dangerBox", "info": "infoBox"}[kind]
        )
        return label


class HistoryDialog(_BaseDialog):
    """عرض سجل العمليات وطلب الاسترجاع."""

    restore_requested = pyqtSignal(dict)

    def __init__(self, batches: list[dict], dark_mode: bool = False, parent=None):
        super().__init__("سجل العمليات", dark_mode, parent)
        self.batches = batches
        self.setMinimumSize(740, 540)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        layout.setSpacing(theme.SPACE_MD)
        layout.addWidget(self.header(
            "undo", "سجل العمليات",
            "كل عملية عزل مسجّلة هنا — اختر عملية لإرجاع ملفاتها إلى مواقعها الأصلية.",
        ))

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)

        for batch in reversed(self.batches):
            status_key = batch.get("status", "")
            status = _STATUS_LABELS.get(status_key, status_key)
            item = QListWidgetItem(textfmt.join([
                textfmt.ltr(batch["timestamp"]),
                textfmt.count_files(batch.get("total_files", 0)),
                textfmt.ltr(format_bytes(batch.get("total_size", 0))),
                status,
            ]))
            item.setIcon(icons.icon(
                _STATUS_ICONS.get(status_key, "clock"), self.p.text_muted, theme.ICON_SM
            ))
            item.setData(Qt.UserRole, batch)
            if batch.get("restored"):
                item.setForeground(QColor(self.p.text_muted))
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget, 1)

        self.details = QLabel("اختر عملية لعرض تفاصيلها.")
        self.details.setObjectName("dryRunSummary")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.details)

        buttons = QHBoxLayout()
        self.restore_btn = apply_variant(QPushButton("إرجاع الملفات"), "primary")
        self.restore_btn.setIcon(
            icons.icon("undo", self.p.text_inverse, theme.ICON_SM, self.p.disabled_text)
        )
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.close)
        buttons.addWidget(self.restore_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _selected_batch(self) -> dict | None:
        items = self.list_widget.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _on_selection_changed(self) -> None:
        batch = self._selected_batch()
        if batch is None:
            self.details.setText("اختر عملية لعرض تفاصيلها.")
            self.restore_btn.setEnabled(False)
            return
        remaining = len(batch.get("operations", []))
        rows = [
            ("التاريخ", textfmt.ltr(batch["timestamp"])),
            ("المجلد المصدر", textfmt.ltr(batch["source_folder"])),
            ("مجلد الوجهة", textfmt.ltr(batch["dest_folder"])),
            (
                "عدد الملفات",
                textfmt.count_files(batch.get("total_files", 0))
                + (f" (متبقٍ للإرجاع: {textfmt.num(remaining)})"
                   if batch.get("status") == STATUS_PARTIAL else ""),
            ),
            ("الحجم الكلي", textfmt.ltr(format_bytes(batch.get("total_size", 0)))),
            ("معرف العملية", textfmt.ltr(batch["operation_id"])),
        ]
        self.details.setText(
            "<table cellspacing='4'>"
            + "".join(
                f"<tr><td style='color:{self.p.text_muted};'>{key}</td>"
                f"<td>&nbsp;&nbsp;{value}</td></tr>"
                for key, value in rows
            )
            + "</table>"
        )
        self.restore_btn.setEnabled(remaining > 0 and not batch.get("restored", False))

    def _on_restore_clicked(self) -> None:
        batch = self._selected_batch()
        if batch is not None:
            self.restore_requested.emit(batch)
            self.close()


class DryRunDialog(_BaseDialog):
    """معاينة إجبارية قبل النقل/الحذف.

    ميزات الأمان:
    - تحذير للعمليات الكبيرة (>100 ملف أو >1GB).
    - حارس الاحتفاظ بنسخة: إذا حُددت كل ملفات مجموعة، لا يُفعّل زر
      التأكيد إلا بعد إقرار صريح — لأن "عزل/حذف كل النسخ" يعني
      عدم بقاء أي نسخة في مكانها الأصلي.
    - تنبيه عندما يكون وضع الكشف لا يضمن تطابق المحتوى.
    """

    def __init__(
        self,
        selected_groups: list[list[dict]],
        action_label: str,
        fully_selected_groups: int = 0,
        content_warning: str = "",
        destructive: bool = False,
        dark_mode: bool = False,
        parent=None,
    ):
        super().__init__(f"معاينة العملية — {action_label}", dark_mode, parent)
        self.selected_groups = selected_groups
        self.confirmed = False
        self.setMinimumSize(860, 600)
        self._build_ui(action_label, fully_selected_groups, content_warning, destructive)

    def _build_ui(
        self, action_label: str, fully_selected: int,
        content_warning: str, destructive: bool,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        layout.setSpacing(theme.SPACE_MD)

        total_files = sum(len(g) for g in self.selected_groups)
        total_size = sum(f["size"] for g in self.selected_groups for f in g)

        layout.addWidget(self.header(
            "trash" if destructive else "archive",
            f"مراجعة قبل التنفيذ — {action_label}",
            "راجع القائمة أدناه بدقة: لا يُنفَّذ أي شيء قبل ضغط زر التأكيد.",
        ))

        summary = QLabel(
            "<table cellspacing='6'>"
            f"<tr><td style='color:{self.p.text_muted};'>الإجراء</td>"
            f"<td>&nbsp;&nbsp;<b>{action_label}</b></td>"
            f"<td width='30'></td>"
            f"<td style='color:{self.p.text_muted};'>المجموعات</td>"
            f"<td>&nbsp;&nbsp;<b>{len(self.selected_groups)}</b></td></tr>"
            f"<tr><td style='color:{self.p.text_muted};'>الملفات</td>"
            f"<td>&nbsp;&nbsp;<b>{total_files}</b></td><td></td>"
            f"<td style='color:{self.p.text_muted};'>الحجم الكلي</td>"
            f"<td>&nbsp;&nbsp;<b>{textfmt.ltr(format_bytes(total_size))}</b></td></tr>"
            "</table>"
        )
        summary.setObjectName("dryRunSummary")
        layout.addWidget(summary)

        if total_files >= LARGE_OP_FILE_COUNT or total_size >= LARGE_OP_SIZE_BYTES:
            layout.addWidget(self.notice(
                "<b>عملية كبيرة</b> — عدد الملفات أو حجمها مرتفع؛ راجع القائمة بعناية "
                "قبل المتابعة."
            ))

        if content_warning:
            layout.addWidget(self.notice(content_warning))

        tree = QTreeWidget()
        tree.setHeaderLabels(["الملف", "الحجم", "النوع", "المسار الكامل"])
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        bold = QFont()
        bold.setBold(True)
        for idx, group in enumerate(self.selected_groups, 1):
            grp_item = QTreeWidgetItem([
                f"مجموعة {textfmt.num(idx)} — {textfmt.count_files(len(group))}",
                textfmt.ltr(format_bytes(sum(f["size"] for f in group))),
                "", "",
            ])
            grp_item.setIcon(0, icons.icon("layers", self.p.text_muted, theme.ICON_SM))
            for col in range(4):
                grp_item.setBackground(col, QColor(self.p.group_row))
                grp_item.setFont(col, bold)
            for f in group:
                child = QTreeWidgetItem([
                    textfmt.ltr(f["name"]),
                    textfmt.ltr(format_bytes(f["size"])),
                    textfmt.ltr(f.get("ext", "")) or "بدون",
                    textfmt.ltr(f["path"]),
                ])
                child.setToolTip(3, f["path"])
                grp_item.addChild(child)
            tree.addTopLevelItem(grp_item)
            grp_item.setExpanded(True)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        tree.setColumnWidth(0, 260)
        layout.addWidget(tree, 1)

        # حارس الاحتفاظ بنسخة
        self.keep_one_ack: QCheckBox | None = None
        if fully_selected > 0:
            layout.addWidget(self.notice(
                f"<b>حُددت كل ملفات {textfmt.count_groups(fully_selected)}</b> — "
                "لن تبقى أي نسخة في "
                "مكانها الأصلي. الأفضل إبقاء نسخة واحدة على الأقل عبر أزرار "
                "«الكل عدا الأحدث / الأقدم».",
                kind="danger",
            ))
            self.keep_one_ack = QCheckBox(
                "أُدرك أنه لن تبقى أي نسخة من هذه المجموعات، وأريد المتابعة"
            )
            self.keep_one_ack.toggled.connect(self._update_confirm_state)
            layout.addWidget(self.keep_one_ack)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("إلغاء")
        cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = apply_variant(
            QPushButton(f"تأكيد — {action_label}"),
            "danger" if destructive else "primary",
        )
        self.confirm_btn.setIcon(icons.icon(
            "trash" if destructive else "check",
            self.p.text_inverse, theme.ICON_SM, self.p.disabled_text,
        ))
        self.confirm_btn.setDefault(True)
        self.confirm_btn.clicked.connect(self._on_confirm)
        # في واجهة من اليمين لليسار يقع الإجراء الأساسي على حرف البداية (اليمين)
        btn_row.addWidget(self.confirm_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)
        self._update_confirm_state()

    def _update_confirm_state(self) -> None:
        ok = self.keep_one_ack is None or self.keep_one_ack.isChecked()
        self.confirm_btn.setEnabled(ok)

    def _on_confirm(self) -> None:
        self.confirmed = True
        self.accept()


class GuideDialog(_BaseDialog):
    """دليل مختصر: الفرق بين أوضاع الكشف وشبكة الأمان والاختصارات."""

    def __init__(self, dark_mode: bool = False, parent=None):
        super().__init__("دليل الاستخدام", dark_mode, parent)
        self.setMinimumSize(680, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        layout.setSpacing(theme.SPACE_MD)
        layout.addWidget(self.header(
            "help", "دليل الاستخدام السريع",
            "ثلاث خطوات، وثلاثة أوضاع كشف، وشبكة أمان تمنع الحذف غير المقصود.",
        ))

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setHtml(self._html())
        layout.addWidget(body, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = apply_variant(QPushButton("فهمت"), "primary")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)

    def _html(self) -> str:
        muted = self.p.text_muted
        accent = self.p.primary
        return f"""
        <div style="font-size:13px; line-height:1.9;">
          <h3 style="color:{accent}; margin-bottom:4px;">خطوات العمل</h3>
          <ol style="margin-top:0;">
            <li><b>اختر المجلد</b> — بالاستعراض، أو بلصق المسار، أو بسحب المجلد
                إلى النافذة.</li>
            <li><b>اضبط وضع الكشف</b> ثم اضغط «بدء البحث» (F5).</li>
            <li><b>حدِّد ما تريد عزله</b> — استخدم «الكل عدا الأحدث» لتبقى نسخة
                واحدة دائماً، ثم «عزل المحدد» أو «سلة المحذوفات».</li>
          </ol>

          <h3 style="color:{accent}; margin-bottom:4px;">أوضاع الكشف</h3>
          <table cellspacing="6" style="font-size:13px;">
            <tr>
              <td><b>حجم متقارب</b></td>
              <td style="color:{muted};">يقارن الأحجام فقط. الأسرع، ومناسب للفرز
                  المبدئي، لكنه <b>لا يضمن</b> تطابق المحتوى.</td>
            </tr>
            <tr>
              <td><b>بصمة جزئية</b></td>
              <td style="color:{muted};">نفس الحجم + بصمة من بداية الملف ونهايته.
                  توازن جيد، وهو الوضع الافتراضي.</td>
            </tr>
            <tr>
              <td><b>SHA-256 كامل</b></td>
              <td style="color:{muted};">يقرأ الملف كاملاً. الأبطأ، ويضمن التطابق
                  الفعلي دون استثناء.</td>
            </tr>
          </table>
          <p style="color:{muted};">«حد التقارب» هو الفرق المسموح بين الأحجام؛
             اتركه على 0 (تطابق دقيق) مع أوضاع البصمة.</p>

          <h3 style="color:{accent}; margin-bottom:4px;">شبكة الأمان</h3>
          <ul style="margin-top:0; color:{muted};">
            <li>معاينة إجبارية تعرض كل ملف قبل التنفيذ.</li>
            <li>إذا حُددت كل ملفات مجموعة، يلزم إقرار صريح — كي لا تفقد كل النسخ.</li>
            <li>العمليات تُسجَّل قبل تنفيذها، فيمكن إرجاعها لاحقاً من «سجل العمليات».</li>
            <li>الحذف يذهب إلى سلة محذوفات النظام، لا حذفاً نهائياً.</li>
            <li>الفلترة تعني ما تراه فقط: العمليات لا تمس أي صف مخفي.</li>
          </ul>

          <h3 style="color:{accent}; margin-bottom:4px;">اختصارات</h3>
          <table cellspacing="6" style="color:{muted}; font-size:13px;">
            <tr><td><b>Ctrl+O</b></td><td>اختيار مجلد</td>
                <td width="20"></td><td><b>F5</b></td><td>بدء البحث</td></tr>
            <tr><td><b>Esc</b></td><td>إيقاف العملية</td>
                <td></td><td><b>Ctrl+F</b></td><td>تصفية النتائج</td></tr>
            <tr><td><b>Ctrl+A</b></td><td>تحديد كل الظاهر</td>
                <td></td><td><b>Ctrl+D</b></td><td>إلغاء التحديد</td></tr>
            <tr><td><b>Ctrl+Shift+N</b></td><td>الكل عدا الأحدث</td>
                <td></td><td><b>Ctrl+Shift+B</b></td><td>الكل عدا الأقدم</td></tr>
            <tr><td><b>Ctrl+M</b></td><td>عزل المحدد</td>
                <td></td><td><b>Ctrl+Shift+Del</b></td><td>إرسال إلى السلة</td></tr>
            <tr><td><b>Ctrl+S</b></td><td>تصدير التقرير</td>
                <td></td><td><b>Ctrl+H</b></td><td>سجل العمليات</td></tr>
            <tr><td><b>Ctrl+T</b></td><td>تبديل الثيم</td>
                <td></td><td><b>Ctrl+L</b></td><td>سجل النشاط</td></tr>
          </table>
        </div>
        """


class AboutDialog(_BaseDialog):
    """حول التطبيق — معلومات مختصرة بلا زخرفة."""

    def __init__(self, icon: QIcon | None = None, dark_mode: bool = False, parent=None):
        super().__init__("حول التطبيق", dark_mode, parent)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG, theme.SPACE_LG
        )
        layout.setSpacing(theme.SPACE_MD)

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_MD)
        if icon is not None and not icon.isNull():
            badge = QLabel()
            badge.setPixmap(icon.pixmap(56, 56))
            row.addWidget(badge, 0, Qt.AlignTop)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(APP_NAME)
        name.setObjectName("emptyTitle")
        name.setWordWrap(True)
        version = QLabel(f"الإصدار {__version__}")
        version.setObjectName("hint")
        text_col.addWidget(name)
        text_col.addWidget(version)
        row.addLayout(text_col, 1)
        layout.addLayout(row)

        info = QLabel(
            f"<div style='line-height:1.8;'>"
            f"<span style='color:{self.p.text_muted};'>المطوّر</span>&nbsp;&nbsp;"
            f"{DEVELOPER}<br>"
            f"<span style='color:{self.p.text_muted};'>البريد</span>&nbsp;&nbsp;"
            f"<a href='mailto:{EMAIL}' style='color:{self.p.primary};'>{EMAIL}</a><br>"
            f"<span style='color:{self.p.text_muted};'>الرخصة</span>&nbsp;&nbsp;MIT"
            f"</div>"
        )
        info.setOpenExternalLinks(True)
        info.setObjectName("dryRunSummary")
        layout.addWidget(info)

        copyright_label = QLabel(COPYRIGHT)
        copyright_label.setObjectName("hint")
        copyright_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(copyright_label)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = apply_variant(QPushButton("إغلاق"), "primary")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)
