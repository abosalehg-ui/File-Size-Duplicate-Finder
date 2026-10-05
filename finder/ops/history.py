"""سجل العمليات مع سجل نوايا (intent log) ويومية لكل ملف ونسخ احتياطية دوّارة.

سجل النوايا: تُكتب الدفعة إلى القرص بحالة in_progress قبل بدء النقل،
فإذا انقطع التطبيق في المنتصف تُوسم الدفعة interrupted عند التحميل التالي
بدل أن تختفي العملية من السجل كلياً.

اليومية (journal): النية وحدها لا تكفي للإرجاع لأنها لا تعرف أي الملفات
نُقلت. لذا يُضاف سطر JSON لكل ملف إلى `journal/<operation_id>.jsonl`
**قبل** نقله (إلحاق O(1) مع fsync، لا إعادة كتابة السجل كاملاً). عند
التحميل التالي تُبنى عمليات الدفعة المنقطعة من يوميتها فتصبح قابلة للإرجاع.
سطر لملف لم يُنقل فعلاً (انقطاع بين الكتابة والنقل) آمن: الإرجاع يجد الملف
في مكانه الأصلي فيعدّه مُرجعاً.

حالات الدفعة (status):
    in_progress → completed → restored / partially_restored
    in_progress → interrupted (اكتُشف انقطاع عند التحميل أو فشلت العملية)
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from ..core.paths import app_data_dir, migrate_legacy_files

HISTORY_FILE = "history.json"
BACKUP_DIR = "history_backups"
JOURNAL_DIR = "journal"
MAX_BACKUPS = 10

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_INTERRUPTED = "interrupted"
STATUS_RESTORED = "restored"
STATUS_PARTIAL = "partially_restored"


class HistoryStore:
    def __init__(self, data_dir: str | None = None):
        if data_dir is None:
            data_dir = app_data_dir()
            migrate_legacy_files(data_dir=data_dir)
        self.data_dir = data_dir
        self.path = os.path.join(self.data_dir, HISTORY_FILE)
        self.batches: list[dict] = []
        self.load()

    # ── تحميل/حفظ ────────────────────────────────────────────────────────
    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    self.batches = json.load(f)
        except (OSError, json.JSONDecodeError):
            self.batches = []
        changed = False
        for b in self.batches:
            # دفعات قديمة (قبل 4.0) بلا status: مكتملة أو مسترجعة
            if "status" not in b:
                b["status"] = STATUS_RESTORED if b.get("restored") else STATUS_COMPLETED
                changed = True
            elif b["status"] == STATUS_IN_PROGRESS:
                self._recover_from_journal(b)
                changed = True
        if changed:
            try:
                self.save()
            except OSError:
                # القراءة تبقى صالحة في الذاكرة؛ الحفظ يُعاد مع أول تغيير لاحق
                return
        self._remove_orphan_journals()

    def save(self) -> None:
        """كتابة ذرّية للسجل. ترمي OSError إن تعذّرت الكتابة — على المستدعي
        أن يقرر (الواجهة مثلاً ترفض بدء النقل إن لم تُحفظ نيته)."""
        os.makedirs(self.data_dir, exist_ok=True)
        self._backup_current()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.batches, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)  # كتابة ذرّية

    def _backup_current(self) -> None:
        if not os.path.exists(self.path):
            return
        backup_dir = os.path.join(self.data_dir, BACKUP_DIR)
        try:
            os.makedirs(backup_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            shutil.copy2(self.path, os.path.join(backup_dir, f"history_{ts}.json"))
            backups = sorted(
                f for f in os.listdir(backup_dir)
                if f.startswith("history_") and f.endswith(".json")
            )
            for old in backups[:-MAX_BACKUPS]:
                try:
                    os.remove(os.path.join(backup_dir, old))
                except OSError:
                    pass
        except OSError:
            pass

    # ── اليومية ──────────────────────────────────────────────────────────
    def _journal_path(self, operation_id: str) -> str:
        return os.path.join(self.data_dir, JOURNAL_DIR, f"{operation_id}.jsonl")

    def append_journal(self, operation_id: str, op: dict) -> None:
        """إلحاق عملية ملف واحد بيومية الدفعة وتثبيتها على القرص.

        يُستدعى من خيط العامل قبل نقل كل ملف؛ لا يلمس self.batches فلا
        يتعارض مع خيط الواجهة. يرمي OSError إن تعذّرت الكتابة، فيتوقف النقل
        بدل أن يُنقل ملف بلا أثر.
        """
        path = self._journal_path(operation_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(op, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def read_journal(self, operation_id: str) -> list[dict]:
        """قراءة اليومية مع تجاهل سطر أخير مبتور (انقطاع أثناء الكتابة)."""
        ops: list[dict] = []
        try:
            with open(self._journal_path(operation_id), encoding="utf-8") as f:
                for line in f:
                    try:
                        op = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(op, dict) and "source" in op and "dest" in op:
                        ops.append(op)
        except OSError:
            pass
        return ops

    def _remove_journal(self, operation_id: str) -> None:
        try:
            os.remove(self._journal_path(operation_id))
        except OSError:
            pass

    def _remove_orphan_journals(self) -> None:
        """حذف يوميات دفعات لم تعد قيد التنفيذ (بقايا انقطاع بعد الحفظ)."""
        journal_dir = os.path.join(self.data_dir, JOURNAL_DIR)
        if not os.path.isdir(journal_dir):
            return
        active = {
            b.get("operation_id") for b in self.batches
            if b.get("status") == STATUS_IN_PROGRESS
        }
        for name in os.listdir(journal_dir):
            if name.endswith(".jsonl") and name[:-len(".jsonl")] not in active:
                try:
                    os.remove(os.path.join(journal_dir, name))
                except OSError:
                    pass

    def _recover_from_journal(self, batch: dict) -> None:
        """بناء عمليات دفعة منقطعة من يوميتها ووسمها interrupted."""
        journaled = self.read_journal(batch.get("operation_id", ""))
        if journaled and not batch.get("operations"):
            batch["operations"] = journaled
            batch["total_files"] = len(journaled)
            batch["total_size"] = sum(op.get("size", 0) for op in journaled)
        batch["status"] = STATUS_INTERRUPTED

    # ── دورة حياة الدفعة ─────────────────────────────────────────────────
    def begin_intent(
        self,
        operation_id: str,
        source_folder: str,
        dest_folder: str,
        planned_files: int,
    ) -> dict:
        """كتابة نية النقل إلى القرص قبل بدء العملية.

        إن فشل الحفظ تُزال الدفعة من الذاكرة ويُعاد رمي OSError، فلا تبدأ
        عملية لا أثر لها على القرص.
        """
        batch = {
            "operation_id": operation_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_folder": source_folder,
            "dest_folder": dest_folder,
            "planned_files": planned_files,
            "total_files": 0,
            "total_size": 0,
            "operations": [],
            "status": STATUS_IN_PROGRESS,
            "restored": False,
        }
        self.batches.append(batch)
        try:
            self.save()
        except OSError:
            self.batches.remove(batch)
            raise
        return batch

    def complete(self, operation_id: str, result: dict) -> None:
        batch = self.find(operation_id)
        if batch is None:
            return
        batch["operations"] = result["operations"]
        batch["total_files"] = result["moved_count"]
        batch["total_size"] = result["total_size"]
        batch["status"] = STATUS_COMPLETED
        self.save()
        # اليومية لم تعد لازمة بعد حفظ العمليات في السجل نفسه
        self._remove_journal(operation_id)

    def mark_failed(self, operation_id: str) -> None:
        """فشلت العملية في منتصفها (استثناء غير متوقع): ما نُقل حتى تلك
        اللحظة يُستعاد من اليومية ويبقى قابلاً للإرجاع."""
        batch = self.find(operation_id)
        if batch is None or batch.get("status") != STATUS_IN_PROGRESS:
            return
        self._recover_from_journal(batch)
        self.save()
        self._remove_journal(operation_id)

    def mark_restore_result(self, operation_id: str, failed_ops: list[dict]) -> None:
        """بعد الاسترجاع: إن لم يبق شيء → restored؛ وإلا تبقى العمليات
        الفاشلة فقط في الدفعة لتكون إعادة المحاولة على المتبقي حصراً."""
        batch = self.find(operation_id)
        if batch is None:
            return
        if failed_ops:
            batch["operations"] = failed_ops
            batch["status"] = STATUS_PARTIAL
            batch["restored"] = False
        else:
            batch["operations"] = []
            batch["status"] = STATUS_RESTORED
            batch["restored"] = True
        self.save()

    def clear(self) -> None:
        """مسح السجل كاملاً مع نسخه الاحتياطية ويومياته (لا يمس الملفات نفسها)."""
        self.batches = []
        for name in (BACKUP_DIR, JOURNAL_DIR):
            shutil.rmtree(os.path.join(self.data_dir, name), ignore_errors=True)
        for path in (self.path, self.path + ".tmp"):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def find(self, operation_id: str) -> dict | None:
        for b in self.batches:
            if b.get("operation_id") == operation_id:
                return b
        return None

    def restorable(self) -> list[dict]:
        return [
            b for b in self.batches
            if b.get("operations")
            and b.get("status") in (STATUS_COMPLETED, STATUS_PARTIAL, STATUS_INTERRUPTED)
        ]
