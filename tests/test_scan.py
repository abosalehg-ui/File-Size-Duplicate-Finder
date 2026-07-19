import os
import sys

import pytest

from finder.core.scan import DEFAULT_EXCLUDE_DIRS, scan_folder


def test_flat_scan_ignores_subdirs(tmp_path, make_file):
    make_file("a.txt", b"1")
    make_file("sub/b.txt", b"2")
    files = scan_folder(str(tmp_path), recursive=False)
    assert [f["name"] for f in files] == ["a.txt"]


def test_recursive_scan(tmp_path, make_file):
    make_file("a.txt", b"1")
    make_file("sub/deep/b.txt", b"2")
    files = scan_folder(str(tmp_path), recursive=True)
    assert {f["name"] for f in files} == {"a.txt", "b.txt"}


def test_excluded_dirs_skipped(tmp_path, make_file):
    make_file("a.txt", b"1")
    make_file("node_modules/dep.js", b"2")
    make_file("custom_skip/c.txt", b"3")
    files = scan_folder(
        str(tmp_path), recursive=True,
        exclude_dirs=frozenset(DEFAULT_EXCLUDE_DIRS | {"custom_skip"}),
    )
    assert {f["name"] for f in files} == {"a.txt"}


def test_file_info_fields(tmp_path, make_file):
    make_file("photo.JPG", b"abc")
    files = scan_folder(str(tmp_path))
    info = files[0]
    assert info["name"] == "photo.JPG"
    assert info["ext"] == ".jpg"  # الامتداد يُوحَّد lowercase
    assert info["size"] == 3
    assert info["mtime"] > 0
    assert os.path.isabs(info["path"]) or info["path"].startswith(str(tmp_path))


@pytest.mark.skipif(sys.platform.startswith("win"), reason="symlinks على ويندوز تحتاج صلاحيات")
def test_symlinked_dir_not_followed(tmp_path, make_file):
    make_file("real/a.txt", b"1")
    os.symlink(tmp_path / "real", tmp_path / "link")
    files = scan_folder(str(tmp_path), recursive=True)
    # يظهر الملف مرة واحدة فقط (عبر المجلد الحقيقي)
    assert len([f for f in files if f["name"] == "a.txt"]) == 1
