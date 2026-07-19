"""مسح المجلدات (مسطح أو متداخل) باستخدام os.scandir.

يُرجع قوائم dict بمفاتيح ثابتة: path, name, size, ext, mtime.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from .cancel import CancelToken

DEFAULT_EXCLUDE_DIRS = frozenset({
    ".git", ".svn", ".hg", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".env", "duplicates_sorted",
    ".history_backup", ".file_finder_cache",
})

# إرسال التقدم كل N ملف لتجنب إغراق المستهلك
_PROGRESS_EVERY = 200


def _entry_info(entry: os.DirEntry) -> dict | None:
    try:
        stat = entry.stat(follow_symlinks=False)
    except OSError:
        return None
    return {
        "path": entry.path,
        "name": entry.name,
        "size": stat.st_size,
        "ext": os.path.splitext(entry.name)[1].lower(),
        "mtime": stat.st_mtime,
    }


def scan_folder(
    folder: str,
    recursive: bool = False,
    exclude_dirs: frozenset = DEFAULT_EXCLUDE_DIRS,
    cancel: CancelToken | None = None,
    progress: Callable[[int], None] | None = None,
) -> list[dict]:
    """جمع معلومات الملفات. `progress(count)` يُستدعى دورياً بعدد الملفات المكتشفة.

    الروابط الرمزية لا تُتبع (لا للمجلدات ولا للملفات) لمنع الحلقات والعدّ المزدوج.
    """
    files: list[dict] = []
    count = 0
    stack = [folder]
    while stack:
        if cancel is not None and cancel.cancelled:
            return files
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel is not None and cancel.cancelled:
                        return files
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if recursive and entry.name not in exclude_dirs:
                                stack.append(entry.path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue
                    info = _entry_info(entry)
                    if info is None:
                        continue
                    files.append(info)
                    count += 1
                    if progress is not None and count % _PROGRESS_EVERY == 0:
                        progress(count)
        except OSError:
            continue
    if progress is not None:
        progress(count)
    return files
