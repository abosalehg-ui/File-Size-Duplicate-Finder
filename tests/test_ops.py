import os

from finder.ops.operations import move_groups, restore_batch


def info(path: str) -> dict:
    return {
        "path": path,
        "name": os.path.basename(path),
        "size": os.path.getsize(path),
        "ext": os.path.splitext(path)[1],
        "mtime": os.path.getmtime(path),
    }


def test_move_creates_group_folders(tmp_path, make_file):
    a = info(make_file("a.txt", b"1"))
    b = info(make_file("b.txt", b"2"))
    result = move_groups([[a, b]], str(tmp_path), "op1")
    assert result["moved_count"] == 2
    assert result["error_files"] == []
    dest_dir = tmp_path / "duplicates_sorted" / "folder_1"
    assert sorted(os.listdir(dest_dir)) == ["a.txt", "b.txt"]
    assert not os.path.exists(a["path"])


def test_move_name_collision_renamed(tmp_path, make_file):
    a = info(make_file("x/same.txt", b"1"))
    b = info(make_file("y/same.txt", b"22"))
    result = move_groups([[a, b]], str(tmp_path), "op2")
    assert result["moved_count"] == 2
    dest_dir = tmp_path / "duplicates_sorted" / "folder_1"
    names = sorted(os.listdir(dest_dir))
    assert "same.txt" in names and "same_1.txt" in names


def test_move_missing_file_reported(tmp_path):
    ghost = {"path": str(tmp_path / "ghost.txt"), "name": "ghost.txt",
             "size": 0, "ext": ".txt", "mtime": 0}
    result = move_groups([[ghost]], str(tmp_path), "op3")
    assert result["moved_count"] == 0
    assert result["error_files"] == ["ghost.txt"]


def test_restore_returns_files(tmp_path, make_file):
    a = info(make_file("a.txt", b"1"))
    original = a["path"]
    batch_result = move_groups([[a, info(make_file("b.txt", b"2"))]],
                               str(tmp_path), "op4")
    batch = {
        "operation_id": "op4",
        "dest_folder": batch_result["dest_folder"],
        "operations": batch_result["operations"],
    }
    restore = restore_batch(batch)
    assert restore["restored_count"] == 2
    assert restore["failed_ops"] == []
    assert os.path.exists(original)
    # المجلدات الفارغة تُنظّف بعد الإرجاع الكامل
    assert not os.path.exists(batch_result["dest_folder"])


def test_restore_collision_gets_suffix(tmp_path, make_file):
    a = info(make_file("a.txt", b"old"))
    result = move_groups([[a, info(make_file("b.txt", b"x"))]], str(tmp_path), "op5")
    # ملف جديد ظهر بنفس المسار الأصلي قبل الإرجاع
    (tmp_path / "a.txt").write_bytes(b"new")
    restore = restore_batch({
        "operation_id": "op5",
        "dest_folder": result["dest_folder"],
        "operations": result["operations"],
    })
    assert restore["restored_count"] == 2
    assert (tmp_path / "a.txt").read_bytes() == b"new"          # الجديد لم يُمس
    assert (tmp_path / "a_restored_1.txt").read_bytes() == b"old"


def test_restore_partial_reports_failed_ops(tmp_path, make_file):
    a = info(make_file("a.txt", b"1"))
    b = info(make_file("b.txt", b"2"))
    result = move_groups([[a, b]], str(tmp_path), "op6")
    # حذف أحد الملفات من الوجهة يدوياً → يفشل إرجاعه
    os.remove(result["operations"][0]["dest"])
    restore = restore_batch({
        "operation_id": "op6",
        "dest_folder": result["dest_folder"],
        "operations": result["operations"],
    })
    assert restore["restored_count"] == 1
    assert len(restore["failed_ops"]) == 1
