import os

from finder.core.fileinfo import FileInfo
from finder.ops.operations import move_groups, restore_batch


def test_move_creates_group_folders(tmp_path, make_file, file_info):
    a = file_info(make_file("a.txt", b"1"))
    b = file_info(make_file("b.txt", b"2"))
    result = move_groups([[a, b]], str(tmp_path), "op1")
    assert result["moved_count"] == 2
    assert result["error_files"] == []
    dest_dir = tmp_path / "duplicates_sorted" / "folder_1"
    assert sorted(os.listdir(dest_dir)) == ["a.txt", "b.txt"]
    assert not os.path.exists(a.path)


def test_move_name_collision_renamed(tmp_path, make_file, file_info):
    a = file_info(make_file("x/same.txt", b"1"))
    b = file_info(make_file("y/same.txt", b"22"))
    result = move_groups([[a, b]], str(tmp_path), "op2")
    assert result["moved_count"] == 2
    dest_dir = tmp_path / "duplicates_sorted" / "folder_1"
    names = sorted(os.listdir(dest_dir))
    assert "same.txt" in names and "same_1.txt" in names


def test_move_missing_file_reported(tmp_path):
    ghost = FileInfo(path=str(tmp_path / "ghost.txt"), name="ghost.txt",
                     size=0, ext=".txt", mtime=0)
    result = move_groups([[ghost]], str(tmp_path), "op3")
    assert result["moved_count"] == 0
    assert result["error_files"] == ["ghost.txt"]


def test_restore_returns_files(tmp_path, make_file, file_info):
    a = file_info(make_file("a.txt", b"1"))
    original = a.path
    batch_result = move_groups([[a, file_info(make_file("b.txt", b"2"))]],
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


def test_restore_collision_gets_suffix(tmp_path, make_file, file_info):
    a = file_info(make_file("a.txt", b"old"))
    result = move_groups([[a, file_info(make_file("b.txt", b"x"))]], str(tmp_path), "op5")
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


def test_restore_partial_reports_failed_ops(tmp_path, make_file, file_info):
    a = file_info(make_file("a.txt", b"1"))
    b = file_info(make_file("b.txt", b"2"))
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


def test_journal_written_before_each_move(tmp_path, make_file, file_info):
    """كل ملف يُسجَّل في اليومية وهو ما زال في مكانه الأصلي (قبل النقل)."""
    a = file_info(make_file("a.txt", b"1"))
    b = file_info(make_file("b.txt", b"2"))
    seen = []

    def journal(op):
        seen.append((op["name"], os.path.exists(op["source"])))

    result = move_groups([[a, b]], str(tmp_path), "op7", journal=journal)
    assert result["moved_count"] == 2
    assert seen == [("a.txt", True), ("b.txt", True)]


def test_journal_failure_stops_before_moving(tmp_path, make_file, file_info):
    a = file_info(make_file("a.txt", b"1"))
    b = file_info(make_file("b.txt", b"2"))
    calls = []

    def journal(op):
        calls.append(op["name"])
        if len(calls) == 2:
            raise OSError("disk full")

    result = move_groups([[a, b]], str(tmp_path), "op8", journal=journal)
    assert result["moved_count"] == 1
    assert result["journal_error"] == "disk full"
    assert os.path.exists(b.path)          # لم يُنقل ملف بلا أثر


def test_cancel_returns_what_was_moved(tmp_path, make_file, file_info):
    from finder.core.cancel import CancelToken

    files = [file_info(make_file(f"f{i}.txt", b"x")) for i in range(5)]
    token = CancelToken()

    def progress(done, total):
        if done == 2:
            token.cancel()

    result = move_groups([files], str(tmp_path), "op9", progress=progress, cancel=token)
    assert result["cancelled"] is True
    assert result["moved_count"] == 2
    assert len(result["operations"]) == 2


def test_restore_counts_never_moved_file_as_in_place(tmp_path, make_file):
    """يومية سُجّل فيها ملف ثم انقطع التطبيق قبل نقله: ليس فشلاً."""
    src = make_file("a.txt", b"1")
    restore = restore_batch({
        "operation_id": "op10",
        "dest_folder": str(tmp_path / "duplicates_sorted"),
        "operations": [{"source": src, "dest": str(tmp_path / "nowhere" / "a.txt"),
                        "name": "a.txt", "size": 1, "group": 1}],
    })
    assert restore["already_in_place"] == 1
    assert restore["failed_ops"] == []


def test_restore_cancel_keeps_remaining(tmp_path, make_file, file_info):
    from finder.core.cancel import CancelToken

    files = [file_info(make_file(f"f{i}.txt", b"x")) for i in range(3)]
    moved = move_groups([files], str(tmp_path), "op11")
    token = CancelToken()
    token.cancel()
    restore = restore_batch({
        "operation_id": "op11",
        "dest_folder": moved["dest_folder"],
        "operations": moved["operations"],
    }, cancel=token)
    assert restore["cancelled"] is True
    assert len(restore["failed_ops"]) == 3
