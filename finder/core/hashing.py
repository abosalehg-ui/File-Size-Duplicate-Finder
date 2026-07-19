"""التجزئة (partial MD5 + full SHA-256) والتنقية المتوازية للمجموعات.

- الإلغاء يُفحص عند كل chunk فيستجيب زر الإيقاف خلال أجزاء من الثانية
  حتى أثناء تجزئة ملف ضخم.
- التنقية تستخدم ThreadPoolExecutor: عمليات القراءة و hashlib تحرر الـ GIL،
  فالتوازي يمنح تسريعاً فعلياً على SSD/NVMe.
"""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable

from .cache import HashCache
from .cancel import CancelToken, OperationCancelled

PARTIAL_HASH_CHUNK = 64 * 1024      # 64KB من بداية ونهاية الملف
FULL_HASH_CHUNK = 1024 * 1024       # قراءة streaming بمقاطع 1MB

MODE_SIZE = "size"
MODE_PARTIAL = "partial"
MODE_FULL = "full"

ProgressFn = Callable[[int, int, str], None]  # (done, total, label)


def compute_partial_hash(
    path: str,
    chunk_size: int = PARTIAL_HASH_CHUNK,
    cancel: CancelToken | None = None,
) -> str | None:
    """MD5 لأول وآخر chunk_size بايت + الحجم (لتمييز البدايات المتطابقة).

    MD5 هنا للفهرسة السريعة لا للأمان؛ المطابقة النهائية في وضع full تتم بـ SHA-256.
    """
    try:
        if cancel is not None:
            cancel.raise_if_cancelled()
        size = os.path.getsize(path)
        h = hashlib.md5()
        with open(path, "rb") as f:
            h.update(f.read(chunk_size))
            if size > 2 * chunk_size:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                f.seek(-chunk_size, os.SEEK_END)
                h.update(f.read(chunk_size))
        h.update(str(size).encode())
        return h.hexdigest()
    except OSError:
        return None


def compute_full_hash(
    path: str,
    chunk_size: int = FULL_HASH_CHUNK,
    cancel: CancelToken | None = None,
) -> str | None:
    """SHA-256 كامل عبر streaming — يفحص الإلغاء عند كل chunk."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _default_workers() -> int:
    return min(8, os.cpu_count() or 4)


def _hash_with_cache(
    finfo: dict,
    kind: str,
    cache: HashCache | None,
    cancel: CancelToken | None,
) -> str | None:
    path = finfo["path"]
    try:
        st = os.stat(path)
    except OSError:
        return None
    mtime, size = st.st_mtime, st.st_size
    if cache is not None:
        cached = cache.get(path, mtime, size, kind)
        if cached is not None:
            return cached
    if kind == "partial":
        value = compute_partial_hash(path, cancel=cancel)
    else:
        value = compute_full_hash(path, cancel=cancel)
    if value is not None and cache is not None:
        cache.set(path, mtime, size, kind, value)
    return value


def _parallel_hash(
    items: list[tuple[int, dict]],
    kind: str,
    cache: HashCache | None,
    cancel: CancelToken | None,
    progress: ProgressFn | None,
    label: str,
    max_workers: int | None,
) -> dict[tuple[int, str], list[dict]]:
    """تجزئة (group_idx, file) بالتوازي وإرجاع دلاء {(group_idx, hash): files}."""
    buckets: dict[tuple[int, str], list[dict]] = {}
    total = len(items)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers or _default_workers()) as ex:
        futures = {
            ex.submit(_hash_with_cache, f, kind, cache, cancel): (gi, f)
            for gi, f in items
        }
        try:
            for fut in as_completed(futures):
                if cancel is not None and cancel.cancelled:
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise OperationCancelled()
                gi, f = futures[fut]
                try:
                    value = fut.result()
                except OperationCancelled:
                    continue
                done += 1
                if progress is not None:
                    progress(done, total, label)
                if value is not None:
                    buckets.setdefault((gi, value), []).append(f)
        except OperationCancelled:
            raise
    return buckets


def refine_groups_by_hash(
    groups: list[list[dict]],
    use_full: bool = False,
    cache: HashCache | None = None,
    cancel: CancelToken | None = None,
    progress: ProgressFn | None = None,
    max_workers: int | None = None,
) -> list[list[dict]]:
    """تنقية مجموعات الحجم إلى مجموعات تطابق فعلي.

    المرحلة 1: partial hash (متوازٍ) يقسّم كل مجموعة إلى دلاء.
    المرحلة 2 (وضع full): SHA-256 كامل (متوازٍ) على الدلاء المرشحة فقط.
    عند الإلغاء تُرمى OperationCancelled بعد إيقاف التجمّع.
    """
    all_files = [(gi, f) for gi, grp in enumerate(groups) for f in grp]
    if not all_files:
        return []

    partial_buckets = _parallel_hash(
        all_files, "partial", cache, cancel, progress, "Partial hash", max_workers
    )

    refined: list[list[dict]] = []
    full_candidates: list[tuple[int, dict]] = []
    # معرّف تسلسلي لكل دلو مرشح حتى لا تختلط دلاء partial المختلفة في المرحلة الثانية
    bucket_id = 0
    for bucket in partial_buckets.values():
        if len(bucket) < 2:
            continue
        if not use_full:
            refined.append(bucket)
        else:
            full_candidates.extend((bucket_id, f) for f in bucket)
            bucket_id += 1

    if not use_full:
        return refined

    full_buckets = _parallel_hash(
        full_candidates, "full", cache, cancel, progress, "SHA-256", max_workers
    )
    for bucket in full_buckets.values():
        if len(bucket) > 1:
            refined.append(bucket)
    return refined
