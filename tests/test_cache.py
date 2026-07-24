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
        assert cache.get("/x/a", 1.0, 100, "partial") == "p"
        assert cache.get("/x/a", 1.0, 100, "full") == "f"
    assert not os.path.exists(legacy)  # يُحذف بعد الترحيل
