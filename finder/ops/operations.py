"""عمليات النقل/الحذف/الاسترجاع — دوال نقية مع callbacks للتقدم والإلغاء."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from collections.abc import Callable

from ..core.cancel import CancelToken

try:
    from send2trash import send2trash
    TRASH_AVAILABLE = True
except ImportError:  # pragma: no cover - يعتمد على بيئة التثبيت
    TRASH_AVAILABLE = False

ProgressFn = Callable[[int, int], None]  # (done, total)

OUTPUT_DIR_NAME = "duplicates_sorted"


def _unique_dest(dest_path: str, suffix: str = "") -> str:
    """إيجاد اسم وجهة غير مستخدم بإضافة عدّاد عند التصادم."""
    if not os.path.exists(dest_path):
        return dest_path
    base, ext = os.path.splitext(dest_path)
    counter = 1
    while True:
        candidate = f"{base}{suffix}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def move_groups(
    selected_groups: list[list[dict]],
    base_folder: str,
    operation_id: str,
    progress: ProgressFn | None = None,
    cancel: CancelToken | None = None,
) -> dict:
    """نقل المجموعات المحددة إلى base_folder/duplicates_sorted/folder_N.

    يُرجع dict نتيجة تتضمن operations (لكل ملف: source/dest/name/size/group)
    حتى لو أُلغيت العملية في المنتصف — ما نُقل فعلاً يُسجَّل دائماً ليبقى
    قابلاً للاسترجاع.
    """
    output_folder = os.path.join(base_folder, OUTPUT_DIR_NAME)
    os.makedirs(output_folder, exist_ok=True)

    operations: list[dict] = []
    error_files: list[str] = []
    total_size = 0
    total = sum(len(g) for g in selected_groups)
    done = 0
    cancelled = False

    for group_idx, group_files in enumerate(selected_groups, 1):
        if cancelled:
            break
        group_folder = os.path.join(output_folder, f"folder_{group_idx}")
        os.makedirs(group_folder, exist_ok=True)

        for finfo in group_files:
            if cancel is not None and cancel.cancelled:
                cancelled = True
                break
            done += 1
            src = finfo["path"]
            try:
                if os.path.isfile(src):
                    dest = _unique_dest(
                        os.path.join(group_folder, os.path.basename(src))
                    )
                    size = os.path.getsize(src)
                    shutil.move(src, dest)
                    operations.append({
                        "source": src,
                        "dest": dest,
                        "name": finfo["name"],
                        "size": size,
                        "group": group_idx,
                    })
                    total_size += size
                else:
                    error_files.append(finfo["name"])
            except OSError as e:
                error_files.append(f"{finfo['name']} ({e})")
            if progress is not None:
                progress(done, total)

    return {
        "operation_id": operation_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_folder": base_folder,
        "dest_folder": output_folder,
        "operations": operations,
        "moved_count": len(operations),
        "error_files": error_files,
        "total_size": total_size,
        "cancelled": cancelled,
    }


def trash_groups(
    selected_groups: list[list[dict]],
    progress: ProgressFn | None = None,
    cancel: CancelToken | None = None,
) -> dict:
    """إرسال الملفات المحددة إلى سلة محذوفات النظام."""
    if not TRASH_AVAILABLE:
        raise RuntimeError("مكتبة send2trash غير مثبتة — نفّذ: pip install send2trash")

    total = sum(len(g) for g in selected_groups)
    trashed: list[str] = []
    failed: list[str] = []
    total_size = 0
    done = 0
    cancelled = False

    for group in selected_groups:
        if cancelled:
            break
        for finfo in group:
            if cancel is not None and cancel.cancelled:
                cancelled = True
                break
            done += 1
            path = finfo["path"]
            try:
                size = os.path.getsize(path) if os.path.exists(path) else 0
                send2trash(path)
                trashed.append(path)
                total_size += size
            except OSError as e:
                failed.append(f"{finfo['name']} ({e})")
            if progress is not None:
                progress(done, total)

    return {
        "trashed_count": len(trashed),
        "trashed_paths": trashed,
        "total_size": total_size,
        "failed": failed,
        "cancelled": cancelled,
    }


def restore_batch(
    batch: dict,
    progress: ProgressFn | None = None,
    cancel: CancelToken | None = None,
) -> dict:
    """إرجاع ملفات دفعة نقل إلى مواقعها الأصلية.

    يُرجع failed_ops (العمليات التي لم تُسترجع) حتى يمكن وسم الدفعة
    كـ"مسترجعة جزئياً" وإتاحة إعادة المحاولة على المتبقي فقط.
    """
    operations = batch["operations"]
    total = len(operations)
    restored_count = 0
    failed_ops: list[dict] = []
    error_names: list[str] = []

    for idx, op in enumerate(operations):
        if cancel is not None and cancel.cancelled:
            failed_ops.extend(operations[idx:])
            break
        try:
            if os.path.exists(op["dest"]):
                os.makedirs(os.path.dirname(op["source"]), exist_ok=True)
                dest_path = _unique_dest(op["source"], suffix="_restored")
                shutil.move(op["dest"], dest_path)
                restored_count += 1
            else:
                failed_ops.append(op)
                error_names.append(op["name"])
        except OSError as e:
            failed_ops.append(op)
            error_names.append(f"{op['name']} ({e})")
        if progress is not None:
            progress(idx + 1, total)

    _cleanup_empty_dirs(batch.get("dest_folder"))

    return {
        "operation_id": batch["operation_id"],
        "restored_count": restored_count,
        "failed_ops": failed_ops,
        "error_files": error_names,
    }


def _cleanup_empty_dirs(dest_folder: str | None) -> None:
    """حذف مجلدات folder_N الفارغة ثم مجلد الوجهة إذا فرغ."""
    if not dest_folder or not os.path.isdir(dest_folder):
        return
    try:
        for item in os.listdir(dest_folder):
            item_path = os.path.join(dest_folder, item)
            if os.path.isdir(item_path) and not os.listdir(item_path):
                os.rmdir(item_path)
        if not os.listdir(dest_folder):
            os.rmdir(dest_folder)
    except OSError:
        pass
