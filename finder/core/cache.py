"""تخزين مؤقت لقيم الـ hash على SQLite.

لماذا SQLite بدل JSON؟ مع مئات آلاف الملفات يصبح ملف JSON واحد
(قراءة/كتابة كاملة في كل بحث) عنق زجاجة وعرضة للتلف عند الانقطاع.
SQLite يوفر كتابة ذرّية، وقراءة كسولة، وحذفاً انتقائياً للمدخلات البائتة.

المفتاح المنطقي: (path) مع إبطال بـ (mtime, size).

إصدار المخطط (`PRAGMA user_version`) يسمح بإبطال قيم حُسبت بخوارزمية
تغيّرت: الإصدار 2 أصلح البصمة الجزئية للملفات بين 64 و128 كيلوبايت،
فتُمسح كل قيم partial القديمة مرة واحدة عند الترقية.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading

from .paths import app_data_dir, migrate_legacy_files

CACHE_DB_FILE = "hash_cache.sqlite3"
LEGACY_JSON_FILE = "hash_cache.legacy.json"

SCHEMA_VERSION = 2
# الكتابات تُجمع في معاملة واحدة وتُثبَّت كل COMMIT_EVERY كتابة: لو انهار
# التطبيق في منتصف تجزئة ضخمة لا يضيع إلا آخر دفعة صغيرة لا الكاش كله.
COMMIT_EVERY = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hashes (
    path    TEXT PRIMARY KEY,
    mtime   REAL NOT NULL,
    size    INTEGER NOT NULL,
    partial TEXT,
    full    TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
"""


class HashCache:
    """كاش hash آمن خيطياً (اتصال واحد + قفل) مع إبطال بـ (mtime, size)."""

    def __init__(self, cache_dir: str | None = None):
        if cache_dir is None:
            base = app_data_dir()
            migrate_legacy_files(data_dir=base)
        else:
            base = cache_dir
        self.path = os.path.join(base, CACHE_DB_FILE)
        self._lock = threading.Lock()
        self._pending_writes = 0
        # يُستخدم من تجمّع خيوط التجزئة → check_same_thread=False مع قفل خارجي
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._upgrade_schema()
        self._conn.commit()
        self._import_legacy_json(base)

    def _upgrade_schema(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 2:
            # البصمة الجزئية القديمة كانت تتجاهل ذيل الملفات بين 64 و128KB
            self._conn.execute("UPDATE hashes SET partial = NULL")
        if version < SCHEMA_VERSION:
            # PRAGMA لا يقبل معاملات ربط؛ القيمة ثابت صحيح من الكود
            self._conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")

    def _import_legacy_json(self, base: str) -> None:
        """ترحيل الكاش القديم (JSON) مرة واحدة ثم حذفه."""
        legacy = os.path.join(base, LEGACY_JSON_FILE)
        if not os.path.exists(legacy):
            return
        try:
            with open(legacy, encoding="utf-8") as f:
                data = json.load(f)
            # البصمة الجزئية في الكاش القديم محسوبة بالخوارزمية السابقة فلا
            # تُستورد؛ البصمة الكاملة (SHA-256) لم تتغير فتُحفظ
            rows = [
                (p, e.get("mtime"), e.get("size"), None, e.get("full"))
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
            self._pending_writes += 1
            if self._pending_writes >= COMMIT_EVERY:
                self._conn.commit()
                self._pending_writes = 0

    def prune_missing(self, limit: int = 50_000) -> int:
        """حذف مدخلات الملفات التي لم تعد موجودة (حتى limit فحصاً لكل استدعاء).

        الفحص يكمل من حيث توقف المرة السابقة (مؤشر rowid محفوظ في جدول meta)
        ويعود للبداية عند نهاية الجدول، فتمر كل المدخلات بالتناوب بدل فحص
        نفس أول limit صف في كل مرة.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'prune_cursor'"
            ).fetchone()
            cursor = row[0] if row else 0
            rows = self._conn.execute(
                "SELECT rowid, path FROM hashes WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (cursor, limit),
            ).fetchall()
        gone = [(path,) for _rowid, path in rows if not os.path.exists(path)]
        next_cursor = rows[-1][0] if len(rows) == limit else 0
        with self._lock:
            if gone:
                self._conn.executemany("DELETE FROM hashes WHERE path = ?", gone)
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES ('prune_cursor', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (next_cursor,),
            )
            self._conn.commit()
            self._pending_writes = 0
        return len(gone)

    def clear(self) -> None:
        """مسح كل البصمات المخزنة وتقليص الملف على القرص."""
        with self._lock:
            self._conn.execute("DELETE FROM hashes")
            self._conn.execute("DELETE FROM meta")
            self._conn.commit()
            self._pending_writes = 0
            self._conn.execute("VACUUM")

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM hashes").fetchone()[0]

    def flush(self) -> None:
        with self._lock:
            self._conn.commit()
            self._pending_writes = 0

    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()

    def __enter__(self) -> HashCache:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
