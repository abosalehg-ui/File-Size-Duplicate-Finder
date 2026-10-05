"""مكان بيانات التطبيق (الكاش والسجل) على كل منصة.

كانت الملفات تُكتب في جذر مجلد المستخدم مباشرة (`~/.file_finder_hash_cache…`،
`~/file_finder_history.json`، `~/.history_backup/`)، فتختلط بملفاته ويصعب
العثور عليها أو تنظيفها. الآن تُجمع في مجلد بيانات التطبيق المعتاد للمنصة،
وتُرحَّل الملفات القديمة إليه مرة واحدة.

الوحدة نقية بلا Qt حتى يستخدمها الـ CLI أيضاً.
"""

from __future__ import annotations

import os
import shutil
import sys

APP_DIR_NAME = "FileSizeDuplicateFinder"
# يتيح توجيه البيانات لمجلد آخر (اختبارات، نسخة محمولة)
DATA_DIR_ENV = "FILE_FINDER_DATA_DIR"

# أسماء الملفات القديمة في جذر مجلد المستخدم → اسمها داخل مجلد البيانات
_LEGACY_NAMES = {
    ".file_finder_hash_cache.sqlite3": "hash_cache.sqlite3",
    ".file_finder_hash_cache.sqlite3-wal": "hash_cache.sqlite3-wal",
    ".file_finder_hash_cache.sqlite3-shm": "hash_cache.sqlite3-shm",
    ".file_finder_hash_cache.json": "hash_cache.legacy.json",
    "file_finder_history.json": "history.json",
    ".history_backup": "history_backups",
}


def app_data_dir() -> str:
    """مجلد بيانات التطبيق (يُنشأ إن لم يوجد)."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        base = override
    elif sys.platform.startswith("win"):
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        base = os.path.join(root, APP_DIR_NAME)
    elif sys.platform == "darwin":
        base = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", APP_DIR_NAME
        )
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share"
        )
        base = os.path.join(root, APP_DIR_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def migrate_legacy_files(home: str | None = None, data_dir: str | None = None) -> list[str]:
    """نقل ملفات الإصدارات السابقة من جذر مجلد المستخدم إلى مجلد البيانات.

    لا يكتب فوق ملف موجود في الوجهة، ويتجاهل الأخطاء (الترحيل تحسين لا شرط).
    يُرجع أسماء ما نُقل.
    """
    home = home or os.path.expanduser("~")
    data_dir = data_dir or app_data_dir()
    moved: list[str] = []
    for old_name, new_name in _LEGACY_NAMES.items():
        src = os.path.join(home, old_name)
        dest = os.path.join(data_dir, new_name)
        if not os.path.exists(src) or os.path.exists(dest):
            continue
        try:
            shutil.move(src, dest)
            moved.append(old_name)
        except OSError:
            pass
    return moved
