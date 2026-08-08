"""تنسيق النصوص في واجهة عربية: عزل الاتجاه وصياغة الأعداد.

المشكلة التي تحلها هذه الوحدة: الواجهة اتجاهها من اليمين، فإذا وُضع نص
لاتيني (مسار، اسم ملف، «331.80 MB») داخل سياق عربي عكسته خوارزمية
الاتجاه ثنائي الجهة فيظهر «MB 331.80» أو «home/user/x.jpg/». الحل هو
تغليف تلك المقاطع بعلامات عزل اتجاه.

وكذلك صياغة الأعداد: العربية تفرّق بين المفرد والمثنى والجمع، و«1 ملفات»
صياغة ركيكة تُقرأ كأنها ترجمة آلية.
"""

from __future__ import annotations

# LRE / PDF: يجبران المقطع على الترتيب من اليسار (مسارات، أحجام، تواريخ)
_LRE, _PDF = "\u202a", "\u202c"
# RLM: يفصل رقمين متجاورين في جملة عربية فلا يتبادلان موضعيهما
_RLM = "\u200f"


def ltr(text: str) -> str:
    """عزل مقطع لاتيني ليُقرأ من اليسار داخل الجملة العربية."""
    if not text:
        return text
    return f"{_LRE}{text}{_PDF}"


def num(value: object) -> str:
    """رقم داخل جملة عربية — يمنع تبادل موضع الأرقام المتجاورة."""
    return f"{value}{_RLM}"


def join(parts: list[str], sep: str = "   ·   ") -> str:
    """ضم مقاطع مختلطة في سطر عربي.

    كل فاصل يُحاط بعلامة RTL، فتُرتَّب المقاطع من اليمين إلى اليسار بترتيب
    كتابتها ولا يقفز رقم من مقطع إلى جانب مقطع آخر.
    """
    return f"{_RLM}{sep}{_RLM}".join(part for part in parts if part)


def count_files(count: int) -> str:
    """صياغة عدد الملفات صياغةً عربية سليمة (مفرد/مثنى/جمع)."""
    if count == 0:
        return "لا ملفات"
    if count == 1:
        return "ملف واحد"
    if count == 2:
        return "ملفان"
    if count <= 10:
        return f"{num(count)} ملفات"
    return f"{num(count)} ملفاً"


def count_groups(count: int) -> str:
    """صياغة عدد المجموعات صياغةً عربية سليمة."""
    if count == 0:
        return "لا مجموعات"
    if count == 1:
        return "مجموعة واحدة"
    if count == 2:
        return "مجموعتان"
    if count <= 10:
        return f"{num(count)} مجموعات"
    return f"{num(count)} مجموعة"
