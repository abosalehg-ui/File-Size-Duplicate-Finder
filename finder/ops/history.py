"""سجل العمليات مع سجل نوايا (intent log) ونسخ احتياطية دوّارة.

سجل النوايا: تُكتب الدفعة إلى القرص بحالة in_progress قبل بدء النقل،
فإذا انقطع التطبيق في المنتصف تُوسم الدفعة interrupted عند التحميل التالي
بدل أن تختفي العملية من السجل كلياً.

حالات الدفعة (status):
    in_progress → completed → restored / partially_restored
    in_progress → interrupted (اكتُشف انقطاع عند التحميل)
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

HISTORY_FILE = "file_finder_history.json"
BACKUP_DIR = ".history_backup"
MAX_BACKUPS = 10

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_INTERRUPTED = "interrupted"
STATUS_RESTORED = "restored"
STATUS_PARTIAL = "partially_restored"


class HistoryStore:
    def __init__(self, home_dir: str | None = None):
        self.home = home_dir or os.path.expanduser("~")
        self.path = os.path.join(self.home, HISTORY_FILE)
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
                b["status"] = STATUS_INTERRUPTED
                changed = True
        if changed:
            self.save()

    def save(self) -> None:
        self._backup_current()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.batches, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)  # كتابة ذرّية

    def _backup_current(self) -> None:
        if not os.path.exists(self.path):
            return
        backup_dir = os.path.join(self.home, BACKUP_DIR)
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

    # ── دورة حياة الدفعة ─────────────────────────────────────────────────
    def begin_intent(
        self,
        operation_id: str,
        source_folder: str,
        dest_folder: str,
        planned_files: int,
    ) -> dict:
        """كتابة نية النقل إلى القرص قبل بدء العملية."""
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
        self.save()
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
