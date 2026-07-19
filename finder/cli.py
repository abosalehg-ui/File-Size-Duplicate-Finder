#!/usr/bin/env python3
"""واجهة سطر الأوامر — تستخدم نفس محرك finder.core الذي تستخدمه الواجهة.

أكواد الخروج:
    0  عُثر على مجموعات متقاربة/مكررة
    1  لم يُعثر على شيء
    2  خطأ في الاستخدام (مسار غير صالح، ...)
    130 أُلغيت العملية (Ctrl+C)

أمثلة:
    file-finder --scan /data --recursive --mode full --output report.csv
    file-finder --scan /data --exclude Backups --exclude tmp --json-cache
"""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .core import (
    DEFAULT_EXCLUDE_DIRS, HashCache, group_by_size, scan_folder,
)
from .core.hashing import MODE_FULL, MODE_PARTIAL, refine_groups_by_hash
from .core.reports import print_text_report, write_report

EXIT_FOUND = 0
EXIT_NONE = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="file-finder",
        description="File Size Duplicate Finder — واجهة سطر الأوامر",
        epilog=(
            "أكواد الخروج: 0 = عُثر على مجموعات، 1 = لا نتائج، "
            "2 = خطأ استخدام، 130 = إلغاء"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--scan", required=True, help="مسار المجلد المراد فحصه")
    parser.add_argument(
        "--threshold", type=float, default=0.0,
        help="حد التقارب بالميجابايت (افتراضي 0 = تطابق حجم دقيق)",
    )
    parser.add_argument("--recursive", action="store_true",
                        help="بحث متداخل في المجلدات الفرعية")
    parser.add_argument("--same-ext", action="store_true", help="نفس الامتداد فقط")
    parser.add_argument(
        "--mode", choices=["size", "partial", "full"], default="size",
        help="وضع الكشف: size (افتراضي) | partial | full",
    )
    parser.add_argument(
        "--exclude", action="append", default=[], metavar="DIR",
        help="اسم مجلد إضافي يُستثنى من المسح (يقبل التكرار)",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="عدد خيوط التجزئة المتوازية (افتراضي: تلقائي)",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="عدم استخدام كاش الـ hash (لا قراءة ولا كتابة)",
    )
    parser.add_argument(
        "--output",
        help="مسار حفظ التقرير (الامتداد يحدد الصيغة: .csv / .json / .txt)",
    )
    parser.add_argument("--quiet", action="store_true",
                        help="عدم طباعة أي مخرجات على الشاشة")
    parser.add_argument("--verbose", action="store_true", help="طباعة تفاصيل التقدم")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isdir(args.scan):
        print(f"خطأ: المسار '{args.scan}' ليس مجلداً صالحاً", file=sys.stderr)
        return EXIT_USAGE

    exclude = frozenset(DEFAULT_EXCLUDE_DIRS | set(args.exclude))

    def vprint(msg: str) -> None:
        if args.verbose and not args.quiet:
            print(msg)

    vprint(f"🔍 جاري فحص: {args.scan}")
    vprint(f"   threshold={args.threshold} MB, recursive={args.recursive}, "
           f"mode={args.mode}")

    try:
        files = scan_folder(args.scan, recursive=args.recursive, exclude_dirs=exclude)
        vprint(f"   تم العثور على {len(files)} ملف")

        groups = group_by_size(
            files,
            threshold_bytes=int(args.threshold * 1024 * 1024),
            same_ext_only=args.same_ext,
        )
        vprint(f"   مجموعات أولية (بالحجم): {len(groups)}")

        if args.mode in (MODE_PARTIAL, MODE_FULL) and groups:
            cache = None if args.no_cache else HashCache()
            try:
                groups = refine_groups_by_hash(
                    groups,
                    use_full=(args.mode == MODE_FULL),
                    cache=cache,
                    max_workers=args.workers,
                )
            finally:
                if cache is not None:
                    cache.close()
            vprint(f"   مجموعات بعد التحقق بالـ hash: {len(groups)}")
    except KeyboardInterrupt:
        print("\nأُلغيت العملية.", file=sys.stderr)
        return EXIT_INTERRUPTED

    if not args.quiet:
        print_text_report(groups)

    if args.output:
        write_report(groups, args.output)
        if not args.quiet:
            print(f"✅ تم حفظ التقرير في: {args.output}")

    return EXIT_FOUND if groups else EXIT_NONE


if __name__ == "__main__":
    sys.exit(main())
