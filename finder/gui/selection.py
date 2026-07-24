"""منطق التحديد النقي — بلا أي اعتماد على Qt، فهو قابل للاختبار مباشرة.

يفصل أخطر منطق في الواجهة (اختيار ما يُحذف/يُعزل، وحالة صندوق المجموعة)
عن عناصر QTreeWidget حتى يُغطّى باختبارات وحدة دون تشغيل واجهة رسومية.
"""

from __future__ import annotations

# حالات صندوق تحديد المجموعة (ثلاثية)
STATE_UNCHECKED = "unchecked"
STATE_CHECKED = "checked"
STATE_PARTIAL = "partial"


def group_tristate(visible: int, checked: int) -> str:
    """حالة صندوق المجموعة انطلاقاً من عدد الأبناء الظاهرين والمحددين منهم.

    تُحتسب العناصر الظاهرة فقط (المخفية بالفلتر لا تُمس)، فإن لم يظهر شيء
    أو لم يُحدَّد شيء فالمجموعة غير محددة، وإن حُدِّد كل الظاهر فهي محددة
    بالكامل، وما بينهما تحديد جزئي.
    """
    if visible == 0 or checked == 0:
        return STATE_UNCHECKED
    if checked >= visible:
        return STATE_CHECKED
    return STATE_PARTIAL


def partition_keep_one(
    files: list[dict], keep: str = "newest"
) -> tuple[list[dict], dict | None]:
    """قسمة ملفات مجموعة إلى (المرشّحة للتحديد، الملف المُحتفظ به).

    يُحتفظ بالأحدث (`keep="newest"`) أو الأقدم (`keep="oldest"`) تعديلاً،
    فتبقى نسخة واحدة دائماً. المجموعة الأصغر من ملفين لا تُنتج تحديداً
    (لا معنى لعزل نسخة وحيدة).

    المقارنة بالهوية (`is`) لا بالقيمة، حتى تعمل بأمان حين تتساوى قواميس
    الملفات (نفس الحجم/الاسم) — يُحتفظ بعنصرٍ واحد بعينه لا بكل المتساوين.
    """
    if len(files) < 2:
        return [], None
    if keep not in ("newest", "oldest"):
        raise ValueError(f"keep غير صالح: {keep!r} (المتوقع 'newest' أو 'oldest')")
    pick = max if keep == "newest" else min
    kept = pick(files, key=lambda f: (f or {}).get("mtime", 0))
    to_select = [f for f in files if f is not kept]
    return to_select, kept
