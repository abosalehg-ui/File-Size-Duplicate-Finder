"""تجميع الملفات المتقاربة بالحجم — نافذة منزلقة O(n log n)."""

from __future__ import annotations


from .cancel import CancelToken
from .fileinfo import FileInfo


def _split_by_extension(group: list[FileInfo]) -> list[list[FileInfo]]:
    by_ext: dict[str, list[FileInfo]] = {}
    for f in group:
        by_ext.setdefault(f.ext, []).append(f)
    return [g for g in by_ext.values() if len(g) > 1]


def group_by_size(
    files: list[FileInfo],
    threshold_bytes: int = 0,
    same_ext_only: bool = False,
    cancel: CancelToken | None = None,
) -> list[list[FileInfo]]:
    """بعد الفرز بالحجم، يُضم كل ملف للمجموعة الحالية إذا كان فرقه عن
    أول ملف فيها (المرساة) ≤ threshold_bytes. عتبة 0 = تطابق حجم دقيق.
    """
    if not files:
        return []

    files = sorted(files, key=lambda x: x.size)
    groups: list[list[FileInfo]] = []
    current: list[FileInfo] = [files[0]]
    anchor = files[0].size

    def flush(bucket: list[FileInfo]) -> None:
        if len(bucket) < 2:
            return
        if same_ext_only:
            groups.extend(_split_by_extension(bucket))
        else:
            groups.append(bucket)

    for f in files[1:]:
        if cancel is not None and cancel.cancelled:
            break
        if f.size - anchor <= threshold_bytes:
            current.append(f)
        else:
            flush(current)
            current = [f]
            anchor = f.size
    flush(current)
    return groups
