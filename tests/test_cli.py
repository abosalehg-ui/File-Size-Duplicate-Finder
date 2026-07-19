import csv
import json

from finder.cli import EXIT_FOUND, EXIT_NONE, EXIT_USAGE, main


def _mkfiles(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"same")
    (tmp_path / "b.txt").write_bytes(b"same")
    (tmp_path / "c.txt").write_bytes(b"different")


def test_finds_duplicates_exit_zero(tmp_path, capsys):
    _mkfiles(tmp_path)
    code = main(["--scan", str(tmp_path), "--mode", "full", "--no-cache"])
    assert code == EXIT_FOUND
    out = capsys.readouterr().out
    assert "a.txt" in out and "b.txt" in out


def test_no_results_exit_one(tmp_path):
    (tmp_path / "only.txt").write_bytes(b"solo")
    assert main(["--scan", str(tmp_path)]) == EXIT_NONE


def test_bad_path_exit_two(tmp_path, capsys):
    assert main(["--scan", str(tmp_path / "nope")]) == EXIT_USAGE
    assert "خطأ" in capsys.readouterr().err


def test_quiet_suppresses_all_output(tmp_path, capsys):
    _mkfiles(tmp_path)
    out_file = tmp_path / "r.json"
    code = main([
        "--scan", str(tmp_path), "--mode", "full", "--no-cache",
        "--output", str(out_file), "--quiet",
    ])
    assert code == EXIT_FOUND
    assert capsys.readouterr().out == ""  # --quiet يكتم كل شيء
    assert out_file.exists()


def test_json_output_structure(tmp_path):
    _mkfiles(tmp_path)
    out_file = tmp_path / "r.json"
    main(["--scan", str(tmp_path), "--mode", "full", "--no-cache",
          "--output", str(out_file), "--quiet"])
    payload = json.loads(out_file.read_text("utf-8"))
    assert payload["groups_count"] == 1
    assert payload["total_files"] == 2
    assert all("mtime" not in f for g in payload["groups"] for f in g)


def test_csv_output(tmp_path):
    _mkfiles(tmp_path)
    out_file = tmp_path / "r.csv"
    main(["--scan", str(tmp_path), "--mode", "full", "--no-cache",
          "--output", str(out_file), "--quiet"])
    with open(out_file, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0][0] == "group"
    assert len(rows) == 3  # عنوان + ملفان


def test_exclude_dir(tmp_path):
    (tmp_path / "keep").mkdir()
    (tmp_path / "skipme").mkdir()
    (tmp_path / "keep" / "a.txt").write_bytes(b"same")
    (tmp_path / "skipme" / "b.txt").write_bytes(b"same")
    code = main(["--scan", str(tmp_path), "--recursive", "--quiet",
                 "--exclude", "skipme"])
    # النسخة الثانية داخل مجلد مستثنى → لا مجموعات
    assert code == EXIT_NONE


def test_threshold_groups_near_sizes(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    (tmp_path / "b.bin").write_bytes(b"y" * 150)
    assert main(["--scan", str(tmp_path), "--quiet"]) == EXIT_NONE
    assert main(["--scan", str(tmp_path), "--quiet", "--threshold", "1"]) == EXIT_FOUND
