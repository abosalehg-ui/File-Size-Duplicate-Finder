"""عمليات الملفات والسجل — نقية (بلا Qt) وقابلة للاختبار."""

from .history import HistoryStore
from .operations import move_groups, restore_batch, trash_groups

__all__ = ["HistoryStore", "move_groups", "restore_batch", "trash_groups"]
