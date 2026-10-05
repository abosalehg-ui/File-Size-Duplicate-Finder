from finder.core.fileinfo import FileInfo


def test_from_path_fields(make_file):
    path = make_file("Photo.JPG", b"abc")
    info = FileInfo.from_path(path)
    assert info.path == path
    assert info.name == "Photo.JPG"
    assert info.ext == ".jpg"
    assert info.size == 3
    assert info.mtime > 0


def test_equality_is_identity():
    # ملفان متطابقا القيم ليسا "نفس الملف" — منطق التحديد يعتمد على ذلك
    a = FileInfo("/x/a", "a", 1, "", 0.0)
    b = FileInfo("/x/a", "a", 1, "", 0.0)
    assert a != b
    assert a == a
    assert len({a, b}) == 2


def test_slots_reject_unknown_attributes():
    info = FileInfo("/x/a", "a", 1, "", 0.0)
    try:
        info.sise = 3   # خطأ إملائي يُكتشف فوراً
    except AttributeError:
        pass
    else:
        raise AssertionError("expected AttributeError")


def test_to_dict_roundtrip():
    info = FileInfo("/x/a.txt", "a.txt", 5, ".txt", 1.5)
    assert info.to_dict() == {
        "path": "/x/a.txt", "name": "a.txt", "size": 5, "ext": ".txt", "mtime": 1.5,
    }
