"""خيط عامل موحد لكل العمليات الطويلة (بحث/نقل/حذف/استرجاع).

بدل أربعة أصناف QThread متطابقة البنية: صنف واحد يشغّل دالة
job(progress, cancel) ويبثّ progress/finished/failed. الإلغاء عبر
CancelToken يصل إلى أعمق حلقات المحرك فيستجيب الإيقاف فوراً.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QThread, pyqtSignal

from ..core.cancel import CancelToken, OperationCancelled

# job: تستقبل (progress_fn(pct:int, msg:str), cancel: CancelToken) وترجع النتيجة
JobFn = Callable[[Callable[[int, str], None], CancelToken], object]


class Worker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, job: JobFn, parent=None):
        super().__init__(parent)
        self._job = job
        self.cancel_token = CancelToken()

    def run(self) -> None:
        try:
            result = self._job(self.progress.emit, self.cancel_token)
        except OperationCancelled:
            self.cancelled.emit()
            return
        except Exception as e:  # noqa: BLE001 - يُعرض للمستخدم في حوار خطأ
            self.failed.emit(str(e))
            return
        if self.cancel_token.cancelled:
            self.cancelled.emit()
        else:
            self.finished_ok.emit(result)

    def stop(self) -> None:
        self.cancel_token.cancel()
