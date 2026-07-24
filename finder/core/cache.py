"""تخزين مؤقت لقيم الـ hash على SQLite.

لماذا SQLite بدل JSON؟ مع مئات آلاف الملفات يصبح ملف JSON واحد
(قراءة/كتابة كاملة في كل بحث) عنق زجاجة وعرضة للتلف عند الانقطاع.
SQLite يوفر كتابة ذرّية، وقراءة كسولة، وحذفاً انتقائياً للمدخلات البائتة.

المفتاح المنطقي: (path) مع إبطال بـ (mtime, size).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

CACHE_DB_FILE = ".file_finder_hash_cache.sqlite3"
LEGACY_JSON_FILE = ".file_finder_hash_cache.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hashes (
    path    TEXT PRIMARY KEY,
    mtime   REAL NOT NULL,
    size    INTEGER NOT NULL,
    partial TEXT,
    full    TEXT
);
"""


class HashCache:
    """كاش hash آمن خيطياً (اتصال واحد + قفل) مع إبطال بـ (mtime, size)."""

    def __init__(self, cache_dir: str | None = None):
        base = cache_dir or os.path.expanduser("~")
        self.path = os.path.join(base, CACHE_DB_FILE)
        self._lock = threading.Lock()
        # يُستخدم من تجمّع خيوط التجزئة → check_same_thread=False مع قفل خارجي
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        self._import_legacy_json(base)

    def _import_legacy_json(self, base: str) -> None:
        """ترحيل الكاش القديم (JSON) مرة واحدة ثم حذفه."""
        legacy = os.path.join(base, LEGACY_JSON_FILE)
        if not os.path.exists(legacy):
            return
        try:
            with open(legacy, encoding="utf-8") as f:
                data = json.load(f)
            rows = [
                (p, e.get("mtime"), e.get("size"), e.get("partial"), e.get("full"))
                for p, e in data.items()
                if isinstance(e, dict) and e.get("mtime") is not None and e.get("size") is not None
            ]
            with self._lock:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO hashes(path, mtime, size, partial, full) "
                    "VALUES (?, ?, ?, ?, ?)",
                    rows,
                )
                self._conn.commit()
            os.remove(legacy)
        except (OSError, json.JSONDecodeError, sqlite3.Error):
            pass

    @staticmethod
    def _check_kind(kind: str) -> None:
        # تحقق صريح (لا assert) حتى يبقى فعّالاً تحت python -O — لأن اسم
        # العمود يُدرَج في نص SQL، فلا يُترك للاعتماد على تعطيلٍ اختياري.
        if kind not in ("partial", "full"):
            raise ValueError(f"kind غير صالح: {kind!r} (المتوقع 'partial' أو 'full')")

    def get(self, path: str, mtime: float, size: int, kind: str) -> str | None:
        """kind: 'partial' أو 'full'. يرجع None إذا لا مدخل أو المدخل بائت."""
        self._check_kind(kind)
        with self._lock:
            row = self._conn.execute(
                f"SELECT mtime, size, {kind} FROM hashes WHERE path = ?", (path,)
            ).fetchone()
        if row is None or row[0] != mtime or row[1] != size:
            return None
        return row[2]

    def set(self, path: str, mtime: float, size: int, kind: str, value: str) -> None:
        self._check_kind(kind)
        other = "full" if kind == "partial" else "partial"
        with self._lock:
            # إذا تغيّر الملف، القيمة الأخرى تصبح بائتة وتُمسح
            self._conn.execute(
                f"INSERT INTO hashes(path, mtime, size, {kind}) VALUES (?, ?, ?, ?) "
                f"ON CONFLICT(path) DO UPDATE SET "
                f"{other} = CASE WHEN mtime = excluded.mtime AND size = excluded.size "
                f"THEN {other} ELSE NULL END, "
                f"mtime = excluded.mtime, size = excluded.size, {kind} = excluded.{kind}",
                (path, mtime, size, value),
            )

    def prune_missing(self, limit: int = 50_000) -> int:
        """حذف مدخلات الملفات التي لم تعد موجودة على القرص (حتى limit فحصاً)."""
        with self._lock:
            paths = [
                r[0]
                for r in self._conn.execute(
                    "SELECT path FROM hashes LIMIT ?", (limit,)
                ).fetchall()
            ]
        gone = [(p,) for p in paths if not os.path.exists(p)]
        if gone:
            with self._lock:
                self._conn.executemany("DELETE FROM hashes WHERE path = ?", gone)
                self._conn.commit()
        return len(gone)

    def flush(self) -> None:
        with self._lock:
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()

    def __enter__(self) -> HashCache:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
