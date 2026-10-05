import json
import os

import pytest

from finder.core.cache import LEGACY_JSON_FILE, HashCache


def test_invalid_kind_rejected(tmp_path):
    # التحقق صريح (ValueError) لا assert — لأن اسم العمود يدخل نص SQL
    with HashCache(str(tmp_path)) as cache:
        with pytest.raises(ValueError):
            cache.get("/x/a", 1.0, 100, "evil")
        with pytest.raises(ValueError):
            cache.set("/x/a", 1.0, 100, "evil", "v")


def test_set_get_roundtrip(tmp_path):
    with HashCache(str(tmp_path)) as cache:
        cache.set("/x/a", 1.0, 100, "partial", "abc")
        assert cache.get("/x/a", 1.0, 100, "partial") == "abc"


def test_stale_entry_returns_none(tmp_path):
    with HashCache(str(tmp_path)) as cache:
        cache.set("/x/a", 1.0, 100, "partial", "abc")
        assert cache.get("/x/a", 2.0, 100, "partial") is None   # تغيّر mtime
        assert cache.get("/x/a", 1.0, 999, "partial") is None   # تغيّر الحجم


def test_update_invalidates_other_kind(tmp_path):
    with HashCache(str(tmp_path)) as cache:
        cache.set("/x/a", 1.0, 100, "partial", "p1")
        cache.set("/x/a", 1.0, 100, "full", "f1")
        # الملف تغيّر: كتابة partial جديد تمسح full البائت
        cache.set("/x/a", 2.0, 100, "partial", "p2")
        assert cache.get("/x/a", 2.0, 100, "full") is None
        assert cache.get("/x/a", 2.0, 100, "partial") == "p2"


def test_persistence_across_reopen(tmp_path):
    with HashCache(str(tmp_path)) as cache:
        cache.set("/x/a", 1.0, 100, "full", "fff")
    with HashCache(str(tmp_path)) as cache2:
        assert cache2.get("/x/a", 1.0, 100, "full") == "fff"


def test_prune_missing(tmp_path, make_file):
    existing = make_file("real.bin", b"data")
    with HashCache(str(tmp_path)) as cache:
        cache.set(existing, 1.0, 4, "partial", "keep")
        cache.set(str(tmp_path / "gone.bin"), 1.0, 4, "partial", "drop")
        removed = cache.prune_missing()
        assert removed == 1
        assert cache.get(existing, 1.0, 4, "partial") == "keep"


def test_legacy_json_import(tmp_path):
    legacy = tmp_path / LEGACY_JSON_FILE
    legacy.write_text(json.dumps({
        "/x/a": {"mtime": 1.0, "size": 100, "partial": "p", "full": "f"},
    }), encoding="utf-8")
    with HashCache(str(tmp_path)) as cache:
        # البصمة الجزئية القديمة محسوبة بالخوارزمية السابقة فلا تُستورد
        assert cache.get("/x/a", 1.0, 100, "partial") is None
        assert cache.get("/x/a", 1.0, 100, "full") == "f"
    assert not os.path.exists(legacy)  # يُحذف بعد الترحيل


def test_schema_upgrade_drops_old_partial_hashes(tmp_path):
    """كاش من إصدار سابق (user_version=0): تُمسح البصمات الجزئية وتبقى الكاملة."""
    import sqlite3

    from finder.core.cache import CACHE_DB_FILE, SCHEMA_VERSION

    conn = sqlite3.connect(str(tmp_path / CACHE_DB_FILE))
    conn.execute(
        "CREATE TABLE hashes (path TEXT PRIMARY KEY, mtime REAL NOT NULL, "
        "size INTEGER NOT NULL, partial TEXT, full TEXT)"
    )
    conn.execute("INSERT INTO hashes VALUES ('/x/a', 1.0, 100, 'old-p', 'f')")
    conn.commit()
    conn.close()

    with HashCache(str(tmp_path)) as cache:
        assert cache.get("/x/a", 1.0, 100, "partial") is None
        assert cache.get("/x/a", 1.0, 100, "full") == "f"
        version = cache._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
    # الترقية مرة واحدة فقط: القيم الجديدة لا تُمسح عند الفتح التالي
    with HashCache(str(tmp_path)) as cache:
        cache.set("/x/a", 1.0, 100, "partial", "new-p")
    with HashCache(str(tmp_path)) as cache:
        assert cache.get("/x/a", 1.0, 100, "partial") == "new-p"


def test_writes_committed_periodically(tmp_path, monkeypatch):
    """الكتابات تُثبَّت كل COMMIT_EVERY دون انتظار close (لا يضيع الكاش عند الانهيار)."""
    import sqlite3

    import finder.core.cache as cache_mod

    monkeypatch.setattr(cache_mod, "COMMIT_EVERY", 3)
    cache = HashCache(str(tmp_path))
    for i in range(3):
        cache.set(f"/x/{i}", 1.0, 1, "full", "v")
    # اتصال مستقل يرى ما ثُبِّت فقط
    other = sqlite3.connect(cache.path)
    assert other.execute("SELECT COUNT(*) FROM hashes").fetchone()[0] == 3
    other.close()
    cache.close()


def test_prune_rotates_through_whole_table(tmp_path):
    """كل استدعاء يكمل من حيث توقف السابق — المدخلات بعد أول limit تُفحص أيضاً."""
    with HashCache(str(tmp_path)) as cache:
        for i in range(6):
            cache.set(str(tmp_path / f"gone{i}.bin"), 1.0, 1, "full", "v")
        removed = [cache.prune_missing(limit=2) for _ in range(3)]
        assert removed == [2, 2, 2]
        assert cache.count() == 0


def test_clear_removes_everything(tmp_path):
    with HashCache(str(tmp_path)) as cache:
        cache.set("/x/a", 1.0, 100, "full", "f")
        cache.clear()
        assert cache.count() == 0
        assert cache.get("/x/a", 1.0, 100, "full") is None


def test_default_location_is_app_data_dir(isolated_data_dir):
    from finder.core.cache import CACHE_DB_FILE

    with HashCache() as cache:
        assert cache.path == str(isolated_data_dir / CACHE_DB_FILE)
