import json
import os

import pytest

from finder.ops.history import (
    BACKUP_DIR, HISTORY_FILE, JOURNAL_DIR, MAX_BACKUPS, STATUS_COMPLETED, STATUS_INTERRUPTED,
    STATUS_PARTIAL, STATUS_RESTORED, HistoryStore,
)


def _result(op_id, n=1):
    return {
        "operation_id": op_id,
        "operations": [{"source": f"/s/{i}", "dest": f"/d/{i}",
                        "name": f"f{i}", "size": 10, "group": 1} for i in range(n)],
        "moved_count": n,
        "total_size": 10 * n,
    }


def test_intent_then_complete(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=2)
    # النية مكتوبة على القرص قبل التنفيذ
    on_disk = json.loads((tmp_path / HISTORY_FILE).read_text("utf-8"))
    assert on_disk[0]["status"] == "in_progress"

    store.complete("op1", _result("op1", n=2))
    assert store.find("op1")["status"] == STATUS_COMPLETED
    assert store.find("op1")["total_files"] == 2


def test_interrupted_detected_on_load(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=1)
    # محاكاة انقطاع: تحميل جديد دون complete
    store2 = HistoryStore(str(tmp_path))
    assert store2.find("op1")["status"] == STATUS_INTERRUPTED


def test_partial_restore_keeps_remaining_ops(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=2)
    store.complete("op1", _result("op1", n=2))
    failed = [store.find("op1")["operations"][1]]
    store.mark_restore_result("op1", failed)
    batch = store.find("op1")
    assert batch["status"] == STATUS_PARTIAL
    assert batch["operations"] == failed
    assert batch["restored"] is False
    assert batch in store.restorable()


def test_full_restore_marks_restored(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=1)
    store.complete("op1", _result("op1"))
    store.mark_restore_result("op1", [])
    batch = store.find("op1")
    assert batch["status"] == STATUS_RESTORED
    assert batch["restored"] is True
    assert batch not in store.restorable()


def test_rolling_backups_capped(tmp_path):
    store = HistoryStore(str(tmp_path))
    for i in range(MAX_BACKUPS + 5):
        store.begin_intent(f"op{i}", "/src", "/dst", planned_files=1)
    backups = os.listdir(tmp_path / BACKUP_DIR)
    assert len(backups) <= MAX_BACKUPS


def test_legacy_batch_migrated(tmp_path):
    legacy = [{
        "operation_id": "old1", "timestamp": "2025-01-01 00:00:00",
        "source_folder": "/s", "dest_folder": "/d",
        "total_files": 1, "total_size": 10,
        "operations": [{"source": "/s/a", "dest": "/d/a", "name": "a", "size": 10}],
        "restored": False,
    }]
    (tmp_path / HISTORY_FILE).write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    store = HistoryStore(str(tmp_path))
    assert store.find("old1")["status"] == STATUS_COMPLETED
    assert store.find("old1") in store.restorable()


def _op(i, tmp="/s", dst="/d"):
    return {"source": f"{tmp}/{i}", "dest": f"{dst}/{i}", "name": f"f{i}",
            "size": 10, "group": 1}


def test_crash_mid_move_recovers_ops_from_journal(tmp_path):
    """انهيار بعد نقل ملفين وقبل complete: الدفعة قابلة للإرجاع عند التحميل التالي."""
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=5)
    store.append_journal("op1", _op(0))
    store.append_journal("op1", _op(1))

    reloaded = HistoryStore(str(tmp_path))
    batch = reloaded.find("op1")
    assert batch["status"] == STATUS_INTERRUPTED
    assert [op["name"] for op in batch["operations"]] == ["f0", "f1"]
    assert batch["total_files"] == 2
    assert batch in reloaded.restorable()
    # بعد الحفظ لم تعد اليومية لازمة
    assert not os.path.exists(tmp_path / JOURNAL_DIR / "op1.jsonl")


def test_truncated_journal_line_ignored(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=2)
    store.append_journal("op1", _op(0))
    with open(tmp_path / JOURNAL_DIR / "op1.jsonl", "a", encoding="utf-8") as f:
        f.write('{"source": "/s/1", "de')   # انقطاع أثناء الكتابة
    batch = HistoryStore(str(tmp_path)).find("op1")
    assert len(batch["operations"]) == 1


def test_complete_removes_journal(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=1)
    store.append_journal("op1", _op(0))
    store.complete("op1", _result("op1"))
    assert not os.path.exists(tmp_path / JOURNAL_DIR / "op1.jsonl")


def test_mark_failed_keeps_journaled_ops_restorable(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=3)
    store.append_journal("op1", _op(0))
    store.mark_failed("op1")
    batch = store.find("op1")
    assert batch["status"] == STATUS_INTERRUPTED
    assert batch in store.restorable()


def test_begin_intent_save_failure_leaves_no_batch(tmp_path, monkeypatch):
    store = HistoryStore(str(tmp_path))

    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", boom)
    with pytest.raises(OSError):
        store.begin_intent("op1", "/src", "/dst", planned_files=1)
    assert store.find("op1") is None


def test_clear_removes_history_backups_and_journals(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.begin_intent("op1", "/src", "/dst", planned_files=1)
    store.begin_intent("op2", "/src", "/dst", planned_files=1)
    store.append_journal("op2", _op(0))
    store.clear()
    assert store.batches == []
    assert not os.path.exists(tmp_path / HISTORY_FILE)
    assert not os.path.exists(tmp_path / BACKUP_DIR)
    assert not os.path.exists(tmp_path / JOURNAL_DIR)
    assert HistoryStore(str(tmp_path)).batches == []


def test_default_location_is_app_data_dir(isolated_data_dir):
    store = HistoryStore()
    assert store.path == str(isolated_data_dir / HISTORY_FILE)
