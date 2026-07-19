from finder.core.formats import format_bytes


def test_bytes_integer_display():
    assert format_bytes(0) == "0 B"
    assert format_bytes(1023) == "1023 B"


def test_kb_mb_gb():
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(5 * 1024 * 1024) == "5.00 MB"
    assert format_bytes(3 * 1024 ** 3) == "3.00 GB"


def test_tb_cap():
    assert format_bytes(2 * 1024 ** 4) == "2.00 TB"
    # أكبر من TB يبقى بوحدة TB
    assert format_bytes(5000 * 1024 ** 4).endswith("TB")
