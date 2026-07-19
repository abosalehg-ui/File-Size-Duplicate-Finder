from finder.core.grouping import group_by_size


def f(name, size, ext=".txt"):
    return {"path": f"/x/{name}", "name": name, "size": size, "ext": ext, "mtime": 0}


def test_exact_match_zero_threshold():
    files = [f("a", 100), f("b", 100), f("c", 101)]
    groups = group_by_size(files, threshold_bytes=0)
    assert len(groups) == 1
    assert {x["name"] for x in groups[0]} == {"a", "b"}


def test_sliding_window_uses_anchor():
    # المرساة أول ملف في المجموعة: 100 و 110 داخل عتبة 10، لكن 121 خارجها
    files = [f("a", 100), f("b", 110), f("c", 121)]
    groups = group_by_size(files, threshold_bytes=10)
    assert len(groups) == 1
    assert {x["name"] for x in groups[0]} == {"a", "b"}


def test_singletons_dropped():
    files = [f("a", 100), f("b", 500), f("c", 900)]
    assert group_by_size(files, threshold_bytes=0) == []


def test_same_ext_split():
    files = [f("a", 100, ".jpg"), f("b", 100, ".jpg"), f("c", 100, ".png")]
    groups = group_by_size(files, threshold_bytes=0, same_ext_only=True)
    assert len(groups) == 1
    assert all(x["ext"] == ".jpg" for x in groups[0])


def test_empty_input():
    assert group_by_size([], threshold_bytes=0) == []
