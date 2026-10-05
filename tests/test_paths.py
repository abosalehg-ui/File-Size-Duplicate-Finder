import os

from finder.core.paths import DATA_DIR_ENV, app_data_dir, migrate_legacy_files


def test_env_override(tmp_path, monkeypatch):
    target = tmp_path / "custom"
    monkeypatch.setenv(DATA_DIR_ENV, str(target))
    assert app_data_dir() == str(target)
    assert target.is_dir()


def test_linux_uses_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert app_data_dir() == str(tmp_path / "xdg" / "FileSizeDuplicateFinder")


def test_migrates_legacy_home_files(tmp_path):
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    (home / "file_finder_history.json").write_text("[]", encoding="utf-8")
    (home / ".file_finder_hash_cache.sqlite3").write_bytes(b"db")
    (home / ".history_backup").mkdir()
    (home / ".history_backup" / "history_1.json").write_text("[]", encoding="utf-8")

    moved = migrate_legacy_files(home=str(home), data_dir=str(data))
    assert set(moved) == {
        "file_finder_history.json", ".file_finder_hash_cache.sqlite3", ".history_backup",
    }
    assert (data / "history.json").exists()
    assert (data / "hash_cache.sqlite3").read_bytes() == b"db"
    assert (data / "history_backups" / "history_1.json").exists()
    assert not os.listdir(home)


def test_migration_never_overwrites(tmp_path):
    home = tmp_path / "home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    (home / "file_finder_history.json").write_text("old", encoding="utf-8")
    (data / "history.json").write_text("new", encoding="utf-8")
    assert migrate_legacy_files(home=str(home), data_dir=str(data)) == []
    assert (data / "history.json").read_text(encoding="utf-8") == "new"
    assert (home / "file_finder_history.json").exists()
