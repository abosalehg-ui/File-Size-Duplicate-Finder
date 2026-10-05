"""تنفيذ العمليات الطويلة: البحث، العزل، السلة، الإرجاع، والتصدير.

كل عملية تمر بنفس المسار: تأكيد/معاينة في خيط الواجهة ← job تعمل في
`Worker` ← معالج نتيجة واحد في خيط الواجهة. قاعدة ثابتة: **كل job ترجع
نتيجة تصل إلى معالجها حتى لو أُوقفت** (النتيجة تحمل `cancelled`)، لأن ما
نُقل قبل الإيقاف يجب أن يُسجَّل؛ الـ job التي لا معنى لنتيجتها الجزئية
(البحث) ترمي OperationCancelled بنفسها.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime

from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from ..core import DEFAULT_EXCLUDE_DIRS, HashCache, format_bytes, group_by_size, scan_folder
from ..core.hashing import MODE_FULL, MODE_PARTIAL, MODE_SIZE, refine_groups_by_hash
from ..core.reports import write_report
from ..ops.operations import (
    OUTPUT_DIR_NAME, TRASH_AVAILABLE, move_groups, restore_batch, trash_groups,
)
from .dialogs import DryRunDialog, HistoryDialog
from .workers import Worker


def _pct_progress(progress, label: str):
    """تحويل تقدّم (done, total) من المحرك إلى (نسبة، رسالة) للواجهة."""
    def report(done: int, total: int) -> None:
        progress(done * 100 // max(total, 1), f"{label}… ({done}/{total})")
    return report


class OperationsMixin:
    """تشغيل العمليات الطويلة وربط نتائجها بالواجهة — يُخلط مع QMainWindow."""

    # ── إدارة الخيوط ─────────────────────────────────────────────────────
    def _spawn(self, job, on_done, on_error=None, on_cancelled=None) -> Worker:
        worker = Worker(job)
        worker.progress.connect(self.on_progress)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_error or self._on_generic_error)
        # لكل عامل معالج إلغاء — بدونه تبقى الواجهة عالقة على «جاري الإيقاف…»
        worker.cancelled.connect(on_cancelled or self._on_generic_cancelled)
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

    def _on_generic_cancelled(self):
        self._set_busy(False)
        self.status_bar.showMessage("تم إيقاف العملية", 5000)
        self.log_message("تم إيقاف العملية", "WARNING")

    # ── البحث ────────────────────────────────────────────────────────────
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
            # المسح والتجميع يرجعان نتيجة جزئية عند الإلغاء؛ عرضها كنتيجة
            # مكتملة مضلِّل، فيُرمى الإلغاء صراحة
            cancel.raise_if_cancelled()
            progress(48, f"تحليل {len(files)} ملف بخوارزمية النافذة المنزلقة…")
            groups = group_by_size(
                files, threshold_bytes=threshold_bytes,
                same_ext_only=same_ext, cancel=cancel,
            )
            cancel.raise_if_cancelled()
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

    # ── العزل في مجلد ────────────────────────────────────────────────────
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

        # سجل النوايا: تُكتب الدفعة قبل بدء النقل حتى لا تضيع لو انقطع التطبيق.
        # إن تعذّرت كتابتها (قرص ممتلئ، صلاحيات) لا يبدأ النقل أصلاً.
        try:
            self.history_store.begin_intent(
                operation_id, folder,
                os.path.join(folder, OUTPUT_DIR_NAME), total_files,
            )
        except OSError as e:
            QMessageBox.critical(
                self, "تعذّر بدء العملية",
                "لم يُنقل أي ملف: تعذّر حفظ سجل العملية، وبدونه لا يمكن "
                f"إرجاع الملفات لاحقاً.\n\n{e}",
            )
            self.log_message(f"تعذّر حفظ سجل العملية: {e}", "ERROR")
            return

        self._set_busy(True)
        self.log_message(f"بدء عملية النقل — {total_files} ملف…")
        history = self.history_store

        def job(progress, cancel):
            return move_groups(
                selected, folder, operation_id,
                progress=_pct_progress(progress, "جاري النقل"),
                cancel=cancel,
                # كل ملف يُسجَّل في يومية الدفعة قبل نقله
                journal=lambda op: history.append_journal(operation_id, op),
            )

        self._spawn(
            job, self.on_move_finished,
            on_error=lambda error: self.on_move_failed(operation_id, error),
        )

    def on_move_finished(self, result: dict):
        moved = result["moved_count"]
        try:
            self.history_store.complete(result["operation_id"], result)
        except OSError as e:
            # اليومية باقية على القرص فتُستعاد الدفعة عند التشغيل التالي
            self.log_message(f"تعذّر حفظ سجل العملية (ستُستعاد لاحقاً): {e}", "ERROR")

        if result.get("journal_error"):
            title = "توقّف النقل"
            message = (
                f"توقّف النقل بعد {moved} ملف لتعذّر تسجيل العملية على القرص:\n"
                f"{result['journal_error']}\n\nالملفات المنقولة قابلة للإرجاع من سجل العمليات."
            )
            level = "ERROR"
        elif result.get("cancelled"):
            title = "أُوقفت العملية"
            message = (
                f"أُوقف النقل بعد {moved} ملف.\n"
                "ما نُقل مسجّل في سجل العمليات ويمكن إرجاعه."
            )
            level = "WARNING"
        else:
            title = "نتيجة العملية"
            message = f"تم نقل {moved} ملف بنجاح إلى:\n{result['dest_folder']}"
            level = "SUCCESS"
        if result["error_files"]:
            message += f"\n\nتعذر نقل {len(result['error_files'])} ملف"
        QMessageBox.information(self, title, message)
        QApplication.beep()
        self.log_message(f"{title} — {moved} ملف", level)
        # تحديث النتائج محلياً بدل إعادة البحث الكامل
        self._remove_paths_from_results(
            {op["source"] for op in result["operations"]}
        )
        self._set_busy(False)

    def on_move_failed(self, operation_id: str, error: str):
        """استثناء غير متوقع أثناء النقل: ما نُقل قبله يُستعاد من اليومية."""
        try:
            self.history_store.mark_failed(operation_id)
        except OSError as e:
            self.log_message(f"تعذّر تحديث سجل العملية: {e}", "ERROR")
        self._on_generic_error(
            f"{error}\n\nالملفات التي نُقلت قبل الخطأ مسجّلة في سجل العمليات."
        )

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
                progress=_pct_progress(progress, "إرسال إلى السلة"),
                cancel=cancel,
            )

        self._spawn(job, self.on_trash_finished)

    def on_trash_finished(self, result: dict):
        count = result["trashed_count"]
        self.log_message(
            f"تم إرسال {count} ملف إلى السلة "
            f"(حجم إجمالي: {format_bytes(result['total_size'])})",
            "WARNING" if result.get("cancelled") else "SUCCESS",
        )
        if result["failed"]:
            self.log_message(f"فشل في {len(result['failed'])} ملف", "WARNING")
        prefix = "أُوقفت العملية — " if result.get("cancelled") else ""
        QMessageBox.information(
            self, "أُوقفت العملية" if result.get("cancelled") else "اكتملت العملية",
            f"{prefix}تم إرسال {count} ملف إلى سلة المحذوفات.\n"
            f"يمكنك استرداد الملفات من سلة محذوفات النظام.",
        )
        self._remove_paths_from_results(set(result["trashed_paths"]))
        self._set_busy(False)

    # ── الإرجاع ──────────────────────────────────────────────────────────
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
        count = len(batch.get("operations", []))
        reply = QMessageBox.question(
            self, "تأكيد الإرجاع",
            f"هل تريد إرجاع {count} ملف إلى مواقعها الأصلية؟",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self._set_busy(True)
        self.log_message(f"بدء إرجاع الملفات — {count} ملف…")

        def job(progress, cancel):
            return restore_batch(
                batch,
                progress=_pct_progress(progress, "جاري الإرجاع"),
                cancel=cancel,
            )

        self._spawn(job, self.on_restore_finished)

    def on_restore_finished(self, result: dict):
        try:
            self.history_store.mark_restore_result(
                result["operation_id"], result["failed_ops"]
            )
        except OSError as e:
            self.log_message(f"تعذّر حفظ نتيجة الإرجاع في السجل: {e}", "ERROR")
        message = f"تم إرجاع {result['restored_count']} ملف بنجاح"
        if result.get("already_in_place"):
            message += (
                f"\n{result['already_in_place']} ملف كان في مكانه الأصلي أصلاً"
            )
        if result.get("cancelled"):
            message = "أُوقف الإرجاع — " + message
        if result["failed_ops"]:
            message += (
                f"\n\nلم يُرجَع {len(result['failed_ops'])} ملف — "
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

    # ── التصدير ──────────────────────────────────────────────────────────
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
        try:
            write_report(self.similar_groups, file_path)
            self.status_bar.showMessage(f"تم حفظ التقرير: {file_path}", 6000)
            self.log_message(f"تم تصدير التقرير: {file_path}", "SUCCESS")
        except OSError as e:
            QMessageBox.critical(self, "خطأ", f"فشل حفظ التقرير:\n{e}")

    # ── بيانات التطبيق (الخصوصية) ────────────────────────────────────────
    def clear_hash_cache(self):
        reply = QMessageBox.question(
            self, "مسح كاش البصمات",
            "سيُحذف كل ما خُزّن من بصمات الملفات ومساراتها.\n"
            "لا تتأثر الملفات نفسها، لكن البحث التالي سيعيد حساب البصمات (أبطأ).\n\n"
            "هل تريد المتابعة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            with HashCache() as cache:
                count = cache.count()
                cache.clear()
        except (OSError, sqlite3.Error) as e:
            QMessageBox.critical(self, "خطأ", f"تعذّر مسح الكاش:\n{e}")
            return
        self.log_message(f"تم مسح كاش البصمات ({count} مدخل)", "SUCCESS")
        self.status_bar.showMessage("تم مسح كاش البصمات", 5000)

    def clear_history(self):
        restorable = len(self.history_store.restorable())
        warning = (
            f"\n\n⚠ في السجل {restorable} عملية ما زالت قابلة للإرجاع — بعد المسح "
            "لن يمكن إرجاع ملفاتها من التطبيق (تبقى في مجلد duplicates_sorted)."
            if restorable else ""
        )
        reply = QMessageBox.warning(
            self, "مسح سجل العمليات",
            "سيُحذف سجل العمليات ونسخه الاحتياطية ومعها مسارات الملفات المسجّلة."
            f"{warning}\n\nهل تريد المتابعة؟",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.history_store.clear()
        except OSError as e:
            QMessageBox.critical(self, "خطأ", f"تعذّر مسح السجل:\n{e}")
            return
        self.log_message("تم مسح سجل العمليات", "SUCCESS")
        self.status_bar.showMessage("تم مسح سجل العمليات", 5000)
