"""تنسيقات العرض المشتركة."""

from __future__ import annotations


def format_bytes(size: float) -> str:
    """تحويل الحجم بالبايت إلى صيغة قابلة للقراءة (B → TB)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"
