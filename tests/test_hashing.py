import hashlib

import pytest

from finder.core.cancel import CancelToken, OperationCancelled
from finder.core.hashing import (
    compute_full_hash, compute_partial_hash, refine_groups_by_hash,
)


def test_identical_files_same_hashes(make_file):
    a = make_file("a.bin", b"hello world" * 100)
    b = make_file("b.bin", b"hello world" * 100)
    assert compute_partial_hash(a) == compute_partial_hash(b)
    assert compute_full_hash(a) == compute_full_hash(b)


def test_different_content_same_size_differs(make_file):
    a = make_file("a.bin", b"A" * 500)
    b = make_file("b.bin", b"B" * 500)
    assert compute_partial_hash(a) != compute_partial_hash(b)
    assert compute_full_hash(a) != compute_full_hash(b)


def test_full_hash_matches_hashlib(make_file):
    content = b"some data" * 1000
    a = make_file("a.bin", content)
    assert compute_full_hash(a) == hashlib.sha256(content).hexdigest()


def test_missing_file_returns_none(tmp_path):
    missing = str(tmp_path / "nope.bin")
    assert compute_partial_hash(missing) is None
    assert compute_full_hash(missing) is None


def test_cancel_raises(make_file):
    a = make_file("a.bin", b"x" * 10)
    token = CancelToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        compute_partial_hash(a, cancel=token)


def test_refine_partial_separates_false_positives(make_file, file_info):
    # ثلاثة ملفات بنفس الحجم: اثنان متطابقان وواحد مختلف
    a = file_info(make_file("a.bin", b"same-content-1234"))
    b = file_info(make_file("b.bin", b"same-content-1234"))
    c = file_info(make_file("c.bin", b"diff-content-1234"))
    refined = refine_groups_by_hash([[a, b, c]], use_full=False)
    assert len(refined) == 1
    assert {x["name"] for x in refined[0]} == {"a.bin", "b.bin"}


def test_refine_full_mode(make_file, file_info):
    a = file_info(make_file("a.bin", b"payload" * 300))
    b = file_info(make_file("b.bin", b"payload" * 300))
    refined = refine_groups_by_hash([[a, b]], use_full=True)
    assert len(refined) == 1
    assert len(refined[0]) == 2


def test_refine_empty():
    assert refine_groups_by_hash([]) == []
