from finder.gui.selection import (
    STATE_CHECKED, STATE_PARTIAL, STATE_UNCHECKED,
    group_tristate, partition_keep_one,
)


def f(name, mtime):
    return {"name": name, "size": 100, "mtime": mtime}


# ── group_tristate ───────────────────────────────────────────────────────
def test_tristate_nothing_visible():
    assert group_tristate(visible=0, checked=0) == STATE_UNCHECKED


def test_tristate_none_checked():
    assert group_tristate(visible=3, checked=0) == STATE_UNCHECKED


def test_tristate_all_checked():
    assert group_tristate(visible=3, checked=3) == STATE_CHECKED


def test_tristate_some_checked():
    assert group_tristate(visible=3, checked=1) == STATE_PARTIAL


# ── partition_keep_one ───────────────────────────────────────────────────
def test_keep_newest_selects_the_rest():
    files = [f("a", 10), f("b", 30), f("c", 20)]
    to_select, kept = partition_keep_one(files, keep="newest")
    assert kept["name"] == "b"                     # الأحدث تعديلاً
    assert {x["name"] for x in to_select} == {"a", "c"}


def test_keep_oldest_selects_the_rest():
    files = [f("a", 10), f("b", 30), f("c", 20)]
    to_select, kept = partition_keep_one(files, keep="oldest")
    assert kept["name"] == "a"                      # الأقدم تعديلاً
    assert {x["name"] for x in to_select} == {"b", "c"}


def test_single_file_selects_nothing():
    to_select, kept = partition_keep_one([f("solo", 5)], keep="newest")
    assert to_select == []
    assert kept is None


def test_identical_dicts_keep_exactly_one():
    # قاموسان متساويان في القيمة: يجب أن يبقى واحد بعينه ويُحدَّد الآخر فقط
    a, b = f("dup", 7), f("dup", 7)
    to_select, kept = partition_keep_one([a, b], keep="newest")
    assert len(to_select) == 1
    assert kept is a or kept is b
    assert to_select[0] is not kept


def test_invalid_keep_raises():
    import pytest
    with pytest.raises(ValueError):
        partition_keep_one([f("a", 1), f("b", 2)], keep="bogus")
