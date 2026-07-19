import json
import os

from finder.ops.history import (
    BACKUP_DIR, MAX_BACKUPS, STATUS_COMPLETED, STATUS_INTERRUPTED,
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
    on_disk = json.loads((tmp_path / "file_finder_history.json").read_text("utf-8"))
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
    (tmp_path / "file_finder_history.json").write_text(
        json.dumps(legacy), encoding="utf-8"
    )
    store = HistoryStore(str(tmp_path))
    assert store.find("old1")["status"] == STATUS_COMPLETED
    assert store.find("old1") in store.restorable()
