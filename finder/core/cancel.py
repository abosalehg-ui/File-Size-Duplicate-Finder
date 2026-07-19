"""إلغاء تعاوني يصل إلى أعمق حلقات العمل (قراءة الملفات chunk بـ chunk)."""

from __future__ import annotations

import threading


class OperationCancelled(Exception):
    """أُلغيت العملية بطلب من المستخدم."""


class CancelToken:
    """علم إلغاء آمن خيطياً تتشاركه الواجهة وخيوط/تجمعات العمل."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelled()
