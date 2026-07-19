"""كتابة التقارير (TXT / CSV / JSON) — مشتركة بين الواجهة والـ CLI."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from typing import TextIO

from .formats import format_bytes


def print_text_report(groups: list[list[dict]], out: TextIO | None = None) -> None:
    # لا نقيّد بـ sys.stdout وقت الاستيراد حتى تعمل إعادة التوجيه (والاختبارات)
    if out is None:
        out = sys.stdout
    if not groups:
        print("لم يتم العثور على ملفات متقاربة.", file=out)
        return
    total_files = sum(len(g) for g in groups)
    total_size = sum(f["size"] for g in groups for f in g)
    print(f"\n{'=' * 70}", file=out)
    print(f"عدد المجموعات: {len(groups)}", file=out)
    print(f"إجمالي الملفات: {total_files}", file=out)
    print(f"الحجم الكلي: {format_bytes(total_size)}", file=out)
    print(f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", file=out)
    print("=" * 70, file=out)
    for i, grp in enumerate(groups, 1):
        gsize = sum(f["size"] for f in grp)
        print(f"\n📁 المجموعة {i} ({len(grp)} ملف، {format_bytes(gsize)}):", file=out)
        for f in grp:
            print(f"  {format_bytes(f['size']):>12}  {f['path']}", file=out)


def write_txt(groups: list[list[dict]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        print_text_report(groups, out=f)


def write_csv(groups: list[list[dict]], path: str) -> None:
    # utf-8-sig: يجعل العربية تظهر صحيحة في Excel
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["group", "name", "size_bytes", "size_readable", "extension", "path"]
        )
        for i, grp in enumerate(groups, 1):
            for x in grp:
                writer.writerow(
                    [i, x["name"], x["size"], format_bytes(x["size"]), x["ext"], x["path"]]
                )


def write_json(groups: list[list[dict]], path: str) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(),
        "groups_count": len(groups),
        "total_files": sum(len(g) for g in groups),
        "total_size_bytes": sum(f["size"] for g in groups for f in g),
        "groups": [
            [{k: v for k, v in f.items() if k != "mtime"} for f in grp]
            for grp in groups
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def write_report(groups: list[list[dict]], path: str) -> None:
    """اختيار الصيغة من الامتداد: .csv / .json / غير ذلك = نص."""
    lower = path.lower()
    if lower.endswith(".csv"):
        write_csv(groups, path)
    elif lower.endswith(".json"):
        write_json(groups, path)
    else:
        write_txt(groups, path)
