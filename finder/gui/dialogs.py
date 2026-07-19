"""حوارات الواجهة: سجل العمليات ومعاينة العملية (Dry-run)."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ..core.formats import format_bytes
from ..ops.history import STATUS_INTERRUPTED, STATUS_PARTIAL

# عتبات تنبيه العمليات الكبيرة
LARGE_OP_FILE_COUNT = 100
LARGE_OP_SIZE_BYTES = 1024 * 1024 * 1024  # 1 GB

_STATUS_LABELS = {
    "completed": "📦 قابل للإرجاع",
    "restored": "✅ تم الإرجاع",
    STATUS_PARTIAL: "⚠️ إرجاع جزئي — متبقٍ",
    STATUS_INTERRUPTED: "⛔ انقطعت — راجعها",
    "in_progress": "⏳ جارية",
}


class HistoryDialog(QDialog):
    """عرض سجل العمليات وطلب الاسترجاع."""

    restore_requested = pyqtSignal(dict)

    def __init__(self, batches: list[dict], parent=None):
        super().__init__(parent)
        self.batches = batches
        self.setWindowTitle("📋 سجل العمليات")
        self.setMinimumSize(700, 500)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)

        for batch in reversed(self.batches):
            status = _STATUS_LABELS.get(batch.get("status", ""), batch.get("status", ""))
            item = QListWidgetItem(
                f"{batch['timestamp']} | "
                f"{batch.get('total_files', 0)} ملف | "
                f"{format_bytes(batch.get('total_size', 0))} | {status}"
            )
            item.setData(Qt.UserRole, batch)
            if batch.get("restored"):
                item.setForeground(QColor("#888888"))
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        layout.addWidget(self.details_text)

        buttons = QHBoxLayout()
        self.restore_btn = QPushButton("🔄 إرجاع الملفات")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.close)
        buttons.addWidget(self.restore_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _selected_batch(self) -> dict | None:
        items = self.list_widget.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _on_selection_changed(self) -> None:
        batch = self._selected_batch()
        if batch is None:
            self.details_text.clear()
            self.restore_btn.setEnabled(False)
            return
        remaining = len(batch.get("operations", []))
        self.details_text.setText(
            f"📅 التاريخ: {batch['timestamp']}\n"
            f"📁 المجلد المصدر: {batch['source_folder']}\n"
            f"📂 مجلد الوجهة: {batch['dest_folder']}\n"
            f"📊 عدد الملفات: {batch.get('total_files', 0)}"
            + (f" (متبقٍ للإرجاع: {remaining})" if batch.get("status") == STATUS_PARTIAL else "")
            + f"\n💾 الحجم الكلي: {format_bytes(batch.get('total_size', 0))}\n"
            f"🔑 معرف العملية: {batch['operation_id']}"
        )
        self.restore_btn.setEnabled(remaining > 0 and not batch.get("restored", False))

    def _on_restore_clicked(self) -> None:
        batch = self._selected_batch()
        if batch is not None:
            self.restore_requested.emit(batch)
            self.close()


class DryRunDialog(QDialog):
    """معاينة إجبارية قبل النقل/الحذف.

    ميزات الأمان:
    - تحذير للعمليات الكبيرة (>100 ملف أو >1GB).
    - حارس الاحتفاظ بنسخة: إذا حُددت كل ملفات مجموعة، لا يُفعّل زر
      التأكيد إلا بعد إقرار صريح — لأن "عزل/حذف كل النسخ" يعني
      عدم بقاء أي نسخة في مكانها الأصلي.
    - تنبيه عندما يكون وضع الكشف بالحجم فقط (التقارب لا يعني تطابق المحتوى).
    """

    def __init__(
        self,
        selected_groups: list[list[dict]],
        action_label: str,
        fully_selected_groups: int = 0,
        size_mode_warning: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.selected_groups = selected_groups
        self.confirmed = False
        self.setWindowTitle(f"📋 معاينة العملية — {action_label}")
        self.setMinimumSize(820, 560)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui(action_label, fully_selected_groups, size_mode_warning)

    def _build_ui(
        self, action_label: str, fully_selected: int, size_mode_warning: bool
    ) -> None:
        layout = QVBoxLayout(self)

        total_files = sum(len(g) for g in self.selected_groups)
        total_size = sum(f["size"] for g in self.selected_groups for f in g)

        summary = QLabel(
            f"<div style='font-size:14px; padding:10px;'>"
            f"🔹 <b>الإجراء:</b> {action_label}<br>"
            f"🔹 <b>عدد المجموعات:</b> {len(self.selected_groups)}<br>"
            f"🔹 <b>إجمالي الملفات:</b> {total_files}<br>"
            f"🔹 <b>الحجم الكلي:</b> {format_bytes(total_size)}</div>"
        )
        summary.setStyleSheet(
            "background-color:#E3F2FD; color:#0d2137; border-radius:8px; "
            "border:1px solid #90CAF9;"
        )
        layout.addWidget(summary)

        if total_files >= LARGE_OP_FILE_COUNT or total_size >= LARGE_OP_SIZE_BYTES:
            layout.addWidget(self._warning_label(
                "⚠️ <b>تنبيه:</b> هذه عملية كبيرة — راجع القائمة بعناية قبل المتابعة."
            ))

        if size_mode_warning:
            layout.addWidget(self._warning_label(
                "⚠️ <b>وضع الكشف الحالي يقارن الأحجام فقط</b> — تقارب الحجم لا يعني "
                "تطابق المحتوى. للتأكد من التكرار الفعلي استخدم وضع Partial أو SHA-256."
            ))

        tree = QTreeWidget()
        tree.setHeaderLabels(["الاسم", "الحجم", "الامتداد", "المسار"])
        tree.setAlternatingRowColors(True)
        for idx, group in enumerate(self.selected_groups, 1):
            grp_item = QTreeWidgetItem([
                f"📁 المجموعة {idx} ({len(group)} ملف)",
                format_bytes(sum(f["size"] for f in group)),
                "", "",
            ])
            for f in group:
                grp_item.addChild(QTreeWidgetItem(
                    [f["name"], format_bytes(f["size"]), f.get("ext", ""), f["path"]]
                ))
            tree.addTopLevelItem(grp_item)
        tree.resizeColumnToContents(0)
        layout.addWidget(tree, 1)

        # حارس الاحتفاظ بنسخة
        self.keep_one_ack: QCheckBox | None = None
        if fully_selected > 0:
            layout.addWidget(self._warning_label(
                f"🛑 <b>حُددت كل ملفات {fully_selected} مجموعة</b> — لن تبقى أي نسخة "
                f"في مكانها الأصلي. يُنصح بإبقاء نسخة واحدة على الأقل "
                f"(استخدم أزرار «تحديد الكل عدا الأحدث/الأقدم»)."
            ))
            self.keep_one_ack = QCheckBox(
                "أُدرك أنه لن تبقى أي نسخة من هذه المجموعات، وأريد المتابعة"
            )
            self.keep_one_ack.toggled.connect(self._update_confirm_state)
            layout.addWidget(self.keep_one_ack)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("❌ إلغاء")
        cancel_btn.clicked.connect(self.reject)
        self.confirm_btn = QPushButton(f"✅ تأكيد — {action_label}")
        self.confirm_btn.setStyleSheet(
            "QPushButton { background-color:#2E7D32; color:white; "
            "padding:8px 18px; border-radius:6px; font-weight:bold; }"
            "QPushButton:hover { background-color:#1B5E20; }"
            "QPushButton:disabled { background-color:#bdc3c7; }"
        )
        self.confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.confirm_btn)
        layout.addLayout(btn_row)
        self._update_confirm_state()

    @staticmethod
    def _warning_label(html: str) -> QLabel:
        label = QLabel(html)
        label.setWordWrap(True)
        label.setStyleSheet(
            "color:#BF360C; background-color:#FFF3E0; padding:8px; "
            "border-radius:6px; border:1px solid #FFAB91;"
        )
        return label

    def _update_confirm_state(self) -> None:
        ok = self.keep_one_ack is None or self.keep_one_ack.isChecked()
        self.confirm_btn.setEnabled(ok)

    def _on_confirm(self) -> None:
        self.confirmed = True
        self.accept()
