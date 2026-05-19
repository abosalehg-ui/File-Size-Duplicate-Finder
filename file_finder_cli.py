#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
واجهة سطر الأوامر (CLI) لـ File Size Duplicate Finder.

يتيح استخدام محرّك البحث من سكربتات أو مهام مجدولة دون الحاجة
لتشغيل الواجهة الرسومية.

أمثلة:
    python -m file_finder_cli --scan /path --threshold 3 --output report.csv
    python -m file_finder_cli --scan /path --recursive --mode partial --json
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from typing import List, Dict

# نستخدم الدوال النقية فقط (بدون PyQt5) من الملف الرئيسي
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# نسخة مستقلة من الدوال النقية لتجنب الاعتماد على PyQt5
def format_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


import hashlib

PARTIAL_HASH_CHUNK = 64 * 1024
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".env", "duplicates_sorted",
}


def compute_partial_hash(path: str) -> str:
    size = os.path.getsize(path)
    h = hashlib.md5()
    with open(path, 'rb') as f:
        h.update(f.read(PARTIAL_HASH_CHUNK))
        if size > 2 * PARTIAL_HASH_CHUNK:
            f.seek(-PARTIAL_HASH_CHUNK, os.SEEK_END)
            h.update(f.read(PARTIAL_HASH_CHUNK))
    h.update(str(size).encode())
    return h.hexdigest()


def compute_full_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def scan_folder(folder: str, recursive: bool, exclude: set) -> List[Dict]:
    files = []
    if recursive:
        stack = [folder]
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name not in exclude:
                                    stack.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                stat = entry.stat(follow_symlinks=False)
                                files.append({
                                    'path': entry.path,
                                    'name': entry.name,
                                    'size': stat.st_size,
                                    'ext': os.path.splitext(entry.name)[1].lower(),
                                    'mtime': stat.st_mtime,
                                })
                        except OSError:
                            continue
            except (PermissionError, OSError):
                continue
    else:
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=False):
                            stat = entry.stat(follow_symlinks=False)
                            files.append({
                                'path': entry.path,
                                'name': entry.name,
                                'size': stat.st_size,
                                'ext': os.path.splitext(entry.name)[1].lower(),
                                'mtime': stat.st_mtime,
                            })
                    except OSError:
                        continue
        except (PermissionError, OSError):
            pass
    return files


def group_sliding_window(files: List[Dict], threshold_mb: float, same_ext: bool) -> List[List[Dict]]:
    if not files:
        return []
    files.sort(key=lambda x: x['size'])
    thr = int(threshold_mb * 1024 * 1024)
    groups = []
    current = [files[0]]
    anchor = files[0]['size']
    for f in files[1:]:
        if f['size'] - anchor <= thr:
            current.append(f)
        else:
            if len(current) > 1:
                if same_ext:
                    by_ext: Dict[str, List[Dict]] = {}
                    for x in current:
                        by_ext.setdefault(x['ext'], []).append(x)
                    for g in by_ext.values():
                        if len(g) > 1:
                            groups.append(g)
                else:
                    groups.append(current)
            current = [f]
            anchor = f['size']
    if len(current) > 1:
        if same_ext:
            by_ext = {}
            for x in current:
                by_ext.setdefault(x['ext'], []).append(x)
            for g in by_ext.values():
                if len(g) > 1:
                    groups.append(g)
        else:
            groups.append(current)
    return groups


def refine_by_hash(groups: List[List[Dict]], full: bool, verbose: bool) -> List[List[Dict]]:
    refined = []
    for grp in groups:
        buckets: Dict[str, List[Dict]] = {}
        for f in grp:
            try:
                ph = compute_partial_hash(f['path'])
                buckets.setdefault(ph, []).append(f)
            except OSError:
                continue
        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            if not full:
                refined.append(bucket)
                continue
            full_buckets: Dict[str, List[Dict]] = {}
            for f in bucket:
                try:
                    fh = compute_full_hash(f['path'])
                    full_buckets.setdefault(fh, []).append(f)
                except OSError:
                    continue
            for sub in full_buckets.values():
                if len(sub) > 1:
                    refined.append(sub)
        if verbose:
            print(f"  مجموعة: {len(grp)} → {sum(1 for b in buckets.values() if len(b) > 1)} bucket(s) متطابق")
    return refined


def print_text_report(groups: List[List[Dict]], out=sys.stdout):
    if not groups:
        print("لم يتم العثور على ملفات متقاربة.", file=out)
        return
    total_files = sum(len(g) for g in groups)
    total_size = sum(f['size'] for g in groups for f in g)
    print(f"\n{'='*70}", file=out)
    print(f"عدد المجموعات: {len(groups)}", file=out)
    print(f"إجمالي الملفات: {total_files}", file=out)
    print(f"الحجم الكلي: {format_bytes(total_size)}", file=out)
    print(f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", file=out)
    print("="*70, file=out)
    for i, grp in enumerate(groups, 1):
        gsize = sum(f['size'] for f in grp)
        print(f"\n📁 المجموعة {i} ({len(grp)} ملف، {format_bytes(gsize)}):", file=out)
        for f in grp:
            print(f"  {format_bytes(f['size']):>12}  {f['path']}", file=out)


def write_csv(groups: List[List[Dict]], path: str):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['group', 'name', 'size_bytes', 'size_readable', 'extension', 'path'])
        for i, grp in enumerate(groups, 1):
            for x in grp:
                writer.writerow([i, x['name'], x['size'], format_bytes(x['size']), x['ext'], x['path']])


def write_json(groups: List[List[Dict]], path: str):
    payload = {
        'generated_at': datetime.now().isoformat(),
        'groups_count': len(groups),
        'total_files': sum(len(g) for g in groups),
        'total_size_bytes': sum(f['size'] for g in groups for f in g),
        'groups': [
            [{k: v for k, v in f.items() if k != 'mtime'} for f in grp]
            for grp in groups
        ],
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="File Size Duplicate Finder — واجهة سطر الأوامر",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--scan", required=True, help="مسار المجلد المراد فحصه")
    parser.add_argument("--threshold", type=float, default=0.0,
                        help="حد التقارب بالميجابايت (افتراضي 0 = تطابق دقيق)")
    parser.add_argument("--recursive", action="store_true", help="بحث متداخل في المجلدات الفرعية")
    parser.add_argument("--same-ext", action="store_true", help="نفس الامتداد فقط")
    parser.add_argument("--mode", choices=["size", "partial", "full"], default="size",
                        help="وضع الكشف: size (افتراضي) | partial | full")
    parser.add_argument("--output", help="مسار حفظ التقرير (الامتداد يحدد الصيغة: .csv / .json / .txt)")
    parser.add_argument("--quiet", action="store_true", help="عدم طباعة التقرير على الشاشة")
    parser.add_argument("--verbose", action="store_true", help="طباعة تفاصيل التقدم")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.scan):
        print(f"خطأ: المسار '{args.scan}' ليس مجلداً صالحاً", file=sys.stderr)
        return 2

    if args.verbose:
        print(f"🔍 جاري فحص: {args.scan}")
        print(f"   threshold={args.threshold} MB, recursive={args.recursive}, mode={args.mode}")

    files = scan_folder(args.scan, args.recursive, DEFAULT_EXCLUDE_DIRS)
    if args.verbose:
        print(f"   تم العثور على {len(files)} ملف")

    groups = group_sliding_window(files, args.threshold, args.same_ext)
    if args.verbose:
        print(f"   مجموعات أولية (بالحجم): {len(groups)}")

    if args.mode in ("partial", "full") and groups:
        groups = refine_by_hash(groups, full=(args.mode == "full"), verbose=args.verbose)
        if args.verbose:
            print(f"   مجموعات بعد التحقق بالـ hash: {len(groups)}")

    if not args.quiet:
        print_text_report(groups)

    if args.output:
        ext = os.path.splitext(args.output)[1].lower()
        if ext == ".csv":
            write_csv(groups, args.output)
        elif ext == ".json":
            write_json(groups, args.output)
        else:
            with open(args.output, 'w', encoding='utf-8') as f:
                print_text_report(groups, out=f)
        print(f"✅ تم حفظ التقرير في: {args.output}")

    return 0 if groups else 1


if __name__ == "__main__":
    sys.exit(main())
