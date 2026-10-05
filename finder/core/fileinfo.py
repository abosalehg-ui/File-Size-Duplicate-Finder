"""سجل معلومات ملف واحد — النوع المشترك بين كل طبقات المشروع.

لماذا dataclass بدل dict؟ القاموس يقبل أي مفتاح، فخطأ إملائي مثل
`f["sise"]` لا يظهر إلا وقت التشغيل وفي أسوأ مكان (أثناء نقل ملفات).
الصنف يحدد الحقول مرة واحدة، و`__slots__` يقلل الذاكرة مع مئات آلاف الملفات.

`eq=False` مقصود: المساواة بالهوية لا بالقيمة. ملفان بنفس الاسم والحجم
والتاريخ في مجلدين مختلفين ليسا "نفس الملف"، ومنطق التحديد
(`partition_keep_one`) يعتمد على أن يبقى عنصر واحد بعينه.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(eq=False)
class FileInfo:
    # __slots__ يدوياً (لا slots=True) لأن المشروع يدعم Python 3.9
    __slots__ = ("path", "name", "size", "ext", "mtime")

    path: str
    name: str
    size: int
    ext: str          # بأحرف صغيرة مع النقطة: ".jpg"، أو "" بلا امتداد
    mtime: float

    @classmethod
    def from_path(cls, path: str) -> FileInfo:
        """بناء السجل من ملف موجود (يتبع الروابط الرمزية مثل os.stat)."""
        st = os.stat(path)
        name = os.path.basename(path)
        return cls(
            path=path,
            name=name,
            size=st.st_size,
            ext=os.path.splitext(name)[1].lower(),
            mtime=st.st_mtime,
        )

    def to_dict(self) -> dict:
        return {field: getattr(self, field) for field in self.__slots__}
