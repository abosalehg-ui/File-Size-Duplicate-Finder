"""اختبارات تنسيق النصوص العربية وعزل الاتجاه (وحدة نقية بلا Qt)."""

from finder.gui.textfmt import count_files, count_groups, join, ltr, num

LRE, PDF, RLM = "\u202a", "\u202c", "\u200f"


def test_ltr_wraps_latin_segment():
    assert ltr("331.80 MB") == f"{LRE}331.80 MB{PDF}"


def test_ltr_keeps_empty_empty():
    """نص فارغ يبقى فارغاً — حتى لا تظهر حقول «—» مغلّفة بعلامات خفية."""
    assert ltr("") == ""


def test_num_marks_number_with_rlm():
    assert num(12) == f"12{RLM}"


def test_count_files_uses_arabic_number_forms():
    assert count_files(0) == "لا ملفات"
    assert count_files(1) == "ملف واحد"
    assert count_files(2) == "ملفان"
    assert count_files(5) == f"5{RLM} ملفات"
    assert count_files(11) == f"11{RLM} ملفاً"


def test_count_groups_uses_arabic_number_forms():
    assert count_groups(0) == "لا مجموعات"
    assert count_groups(1) == "مجموعة واحدة"
    assert count_groups(2) == "مجموعتان"
    assert count_groups(4) == f"4{RLM} مجموعات"
    assert count_groups(20) == f"20{RLM} مجموعة"


def test_join_separates_segments_with_rtl_mark():
    """الفاصل يحمل علامة RTL فلا يقفز رقم من مقطع إلى جانب مقطع آخر."""
    line = join(["أ", "ب"], sep=" · ")
    assert line == f"أ{RLM} · {RLM}ب"


def test_join_drops_empty_segments():
    assert join(["أ", "", "ب"], sep="|") == f"أ{RLM}|{RLM}ب"
