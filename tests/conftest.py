import pytest


@pytest.fixture
def make_file(tmp_path):
    """إنشاء ملف باسم ومحتوى محددين داخل tmp_path (يدعم مجلدات فرعية)."""
    def _make(name: str, content: bytes = b"x") -> str:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)
    return _make
