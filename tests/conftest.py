import os

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


@pytest.fixture
def file_info():
    """بناء dict معلومات ملف من مساره على القرص (بديل موحّد لدوال info المكررة)."""
    def _info(path: str) -> dict:
        return {
            "path": path,
            "name": os.path.basename(path),
            "size": os.path.getsize(path),
            "ext": os.path.splitext(path)[1],
            "mtime": os.path.getmtime(path),
        }
    return _info
