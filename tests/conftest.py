import pytest

from finder.core.fileinfo import FileInfo


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    """كل اختبار يكتب الكاش والسجل في مجلد مؤقت، لا في مجلد المستخدم الحقيقي."""
    data_dir = tmp_path_factory.mktemp("app-data")
    monkeypatch.setenv("FILE_FINDER_DATA_DIR", str(data_dir))
    return data_dir


@pytest.fixture
def make_file(tmp_path):
    """إنشاء ملف باسم ومحتوى محددين داخل tmp_path (يدعم مجلدات فرعية)."""
    def _make(name: str, content: bytes = b"x") -> str:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)
    return _make


@pytest.fixture
def file_info():
    """بناء FileInfo لملف موجود على القرص."""
    return FileInfo.from_path
