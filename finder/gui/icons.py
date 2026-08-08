"""نظام أيقونات متجهة موحّد.

بديل عن الإيموجي المبعثرة في النصوص:

- كل أيقونة مسار SVG بمقاس 24×24 وسماكة خط واحدة (نفس العائلة البصرية).
- تُلوَّن وقت الرسم بلون الثيم الحالي، فتتبع الوضع الفاتح/الداكن تلقائياً.
- ``icon()`` تُرجع ``QIcon`` مع حالة معطّلة باهتة، مُخزَّنة في ذاكرة مؤقتة.
- ``qss_asset()`` تكتب الأيقونة ملفاً مؤقتاً لاستخدامها داخل QSS
  (أسهم القوائم المنسدلة، مؤشرات الشجرة، أزرار العدّاد).

إن غابت ``PyQt5.QtSvg`` لأي سبب تعود الدالة بأيقونة فارغة، فتظل الأزرار
مقروءة بنصوصها ولا تنكسر الواجهة.
"""

from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from PyQt5.QtCore import QByteArray, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap

try:  # QtSvg جزء من PyQt5 القياسي، لكن نحتاط لبيئات مقلّمة
    from PyQt5.QtSvg import QSvgRenderer

    SVG_AVAILABLE = True
except ImportError:  # pragma: no cover - يعتمد على بيئة التشغيل
    SVG_AVAILABLE = False

_SVG_TEMPLATE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
    'width="24" height="24" fill="{fill}" stroke="{stroke}" '
    'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
    "{body}</svg>"
)

# ── مسارات الأيقونات ─────────────────────────────────────────────────────
# القيمة إمّا نص المسار (خط بسماكة 2) أو (نص المسار, "fill") للأشكال المملوءة.
_PATHS: dict[str, str | tuple[str, str]] = {
    # الملفات والمجلدات
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "folder-open": (
        '<path d="M3 8V6a2 2 0 0 1 2-2h4l2 3h8a2 2 0 0 1 2 2v1"/>'
        '<path d="M2.4 12.6A1 1 0 0 1 3.4 11h17.2a1 1 0 0 1 1 1.2l-1.3 6.6A2 2 0 0 1 18.3 21H5.7a2 2 0 0 1-2-1.6z"/>'
    ),
    "file": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
    ),
    "image": (
        '<rect x="3" y="3" width="18" height="18" rx="2"/>'
        '<circle cx="8.5" cy="8.5" r="1.5"/>'
        '<polyline points="21 15 16 10 5 21"/>'
    ),
    "layers": (
        '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
        '<polyline points="2 17 12 22 22 17"/>'
        '<polyline points="2 12 12 17 22 12"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="13" height="13" rx="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "hard-drive": (
        '<line x1="22" y1="12" x2="2" y2="12"/>'
        '<path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
        '<line x1="6" y1="16" x2="6.01" y2="16"/>'
        '<line x1="10" y1="16" x2="10.01" y2="16"/>'
    ),
    # الإجراءات
    "search": '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.2" y2="16.2"/>',
    "stop": ('<rect x="5" y="5" width="14" height="14" rx="2.5"/>', "fill"),
    "archive": (
        '<rect x="2" y="4" width="20" height="5" rx="1.5"/>'
        '<path d="M4 9v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/>'
        '<line x1="10" y1="14" x2="14" y2="14"/>'
    ),
    "trash": (
        '<polyline points="3 6 21 6"/>'
        '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>'
        '<line x1="10" y1="11" x2="10" y2="17"/>'
        '<line x1="14" y1="11" x2="14" y2="17"/>'
        '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>'
    ),
    "undo": (
        '<polyline points="1 4 1 10 7 10"/>'
        '<path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>'
    ),
    "refresh": (
        '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/>'
        '<path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>'
    ),
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'
    ),
    "external": (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
        '<polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>'
    ),
    # التحديد
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "check-square": (
        '<polyline points="9 11 12 14 21 5"/>'
        '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'
    ),
    "square": '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/>',
    "wand": (
        '<path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/>'
        '<path d="M17.8 11.8 19 13"/><path d="M15 9h0"/><path d="M17.8 6.2 19 5"/>'
        '<path d="m3 21 9-9"/><path d="M12.2 6.2 11 5"/>'
    ),
    # العرض والثيم
    "sun": (
        '<circle cx="12" cy="12" r="4.5"/>'
        '<line x1="12" y1="1.5" x2="12" y2="3.5"/><line x1="12" y1="20.5" x2="12" y2="22.5"/>'
        '<line x1="4.2" y1="4.2" x2="5.6" y2="5.6"/><line x1="18.4" y1="18.4" x2="19.8" y2="19.8"/>'
        '<line x1="1.5" y1="12" x2="3.5" y2="12"/><line x1="20.5" y1="12" x2="22.5" y2="12"/>'
        '<line x1="4.2" y1="19.8" x2="5.6" y2="18.4"/><line x1="18.4" y1="5.6" x2="19.8" y2="4.2"/>'
    ),
    "moon": '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    "filter": ('<polygon points="21 4 3 4 10 12.5 10 19 14 21 14 12.5 21 4"/>', "fill"),
    "x": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "expand": '<polyline points="6 9 12 15 18 9"/>',
    "collapse": '<polyline points="18 15 12 9 6 15"/>',
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    "chevron-up": '<polyline points="18 15 12 9 6 15"/>',
    "chevron-left": '<polyline points="15 18 9 12 15 6"/>',
    "chevron-right": '<polyline points="9 18 15 12 9 6"/>',
    "minus": '<line x1="6" y1="12" x2="18" y2="12"/>',
    # المعلومات
    "info": (
        '<circle cx="12" cy="12" r="9.5"/>'
        '<line x1="12" y1="11" x2="12" y2="16.5"/><line x1="12" y1="7.5" x2="12.01" y2="7.5"/>'
    ),
    "help": (
        '<circle cx="12" cy="12" r="9.5"/>'
        '<path d="M9.2 9.2a2.8 2.8 0 0 1 5.5.8c0 1.9-2.8 2.3-2.8 4"/>'
        '<line x1="12" y1="17.5" x2="12.01" y2="17.5"/>'
    ),
    "alert": (
        '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
        '<line x1="12" y1="9" x2="12" y2="13.5"/><line x1="12" y1="17" x2="12.01" y2="17"/>'
    ),
    "shield": (
        '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
        '<polyline points="9 11.5 11.5 14 15.5 9.5"/>'
    ),
    "clock": '<circle cx="12" cy="12" r="9.5"/><polyline points="12 6.5 12 12 16 14"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "sliders": (
        '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/>'
        '<line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/>'
        '<line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/>'
        '<line x1="1.5" y1="14" x2="6.5" y2="14"/><line x1="9.5" y1="8" x2="14.5" y2="8"/>'
        '<line x1="17.5" y1="16" x2="22.5" y2="16"/>'
    ),
    "savings": (
        '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/>'
        '<polyline points="16 17 22 17 22 11"/>'
    ),
    "power": (
        '<path d="M18.4 5.6a9 9 0 1 1-12.8 0"/><line x1="12" y1="2.5" x2="12" y2="11"/>'
    ),
    "eye": (
        '<path d="M1.5 12S5 5.5 12 5.5 22.5 12 22.5 12 19 18.5 12 18.5 1.5 12 1.5 12z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "hash": (
        '<line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/>'
        '<line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/>'
    ),
    "ruler": (
        '<path d="M2.5 15.5 8.5 21.5a1.5 1.5 0 0 0 2.1 0L21.5 10.6a1.5 1.5 0 0 0 0-2.1L15.5 2.5a1.5 1.5 0 0 0-2.1 0L2.5 13.4a1.5 1.5 0 0 0 0 2.1z"/>'
        '<line x1="7" y1="15" x2="9" y2="17"/><line x1="10" y1="12" x2="12" y2="14"/>'
        '<line x1="13" y1="9" x2="15" y2="11"/>'
    ),
    "tag": (
        '<path d="M20.6 13.4 12 22l-9-9V4a1 1 0 0 1 1-1h8.6z"/>'
        '<line x1="7.5" y1="7.5" x2="7.51" y2="7.5"/>'
    ),
    "tree": (
        '<line x1="20" y1="5" x2="9" y2="5"/><line x1="20" y1="12" x2="12" y2="12"/>'
        '<line x1="20" y1="19" x2="12" y2="19"/><path d="M5 3v14a2 2 0 0 0 2 2h5"/>'
        '<path d="M5 12h7"/>'
    ),
}

_STROKE_ONLY = "none"


def _svg_source(name: str, color: str, stroke_width: float = 1.9) -> str | None:
    entry = _PATHS.get(name)
    if entry is None:
        return None
    if isinstance(entry, tuple):
        body, style = entry
    else:
        body, style = entry, "stroke"
    if style == "fill":
        return _SVG_TEMPLATE.format(
            fill=color, stroke=_STROKE_ONLY, width=0, body=body
        )
    return _SVG_TEMPLATE.format(
        fill=_STROKE_ONLY, stroke=color, width=stroke_width, body=body
    )


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18, ratio: int = 2) -> QPixmap:
    """رسم الأيقونة على ``QPixmap`` شفاف (مضروب في ``ratio`` لشاشات Retina)."""
    source = _svg_source(name, color)
    if source is None or not SVG_AVAILABLE:
        return QPixmap()
    px = QPixmap(size * ratio, size * ratio)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    QSvgRenderer(QByteArray(source.encode("utf-8"))).render(
        painter, QRectF(0, 0, size * ratio, size * ratio)
    )
    painter.end()
    px.setDevicePixelRatio(ratio)
    return px


@lru_cache(maxsize=512)
def icon(name: str, color: str, size: int = 18, disabled_color: str = "") -> QIcon:
    """``QIcon`` بلون الثيم، مع حالة معطّلة باهتة إن مُرِّر ``disabled_color``."""
    result = QIcon()
    normal = pixmap(name, color, size)
    if normal.isNull():
        return result
    result.addPixmap(normal, QIcon.Normal)
    if disabled_color:
        result.addPixmap(pixmap(name, disabled_color, size), QIcon.Disabled)
    return result


@lru_cache(maxsize=64)
def swatch(color: str, size: int = 12, radius: int = 3) -> QPixmap:
    """مربّع لون صغير — يُستخدم كعلامة تمييز للمجموعات في الشجرة."""
    ratio = 2
    px = QPixmap(size * ratio, size * ratio)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(
        QRectF(0, 0, size * ratio, size * ratio), radius * ratio, radius * ratio
    )
    painter.end()
    px.setDevicePixelRatio(ratio)
    return px


# ── أصول QSS ─────────────────────────────────────────────────────────────
_ASSET_DIR: Path | None = None


def _asset_dir() -> Path:
    global _ASSET_DIR
    if _ASSET_DIR is None:
        _ASSET_DIR = Path(tempfile.mkdtemp(prefix="fsdf-icons-"))
    return _ASSET_DIR


@lru_cache(maxsize=128)
def qss_asset(name: str, color: str, size: int = 14) -> str:
    """كتابة الأيقونة ملفاً ثم إرجاع مسارها لاستخدامه في ``image: url(...)``.

    QSS لا يقبل SVG مضمّناً، لذا نكتب PNG مؤقتاً. المسار بفواصل ``/``
    ليعمل على Windows أيضاً. تُرجع نصاً فارغاً إذا فشل الرسم.
    """
    px = pixmap(name, color, size, ratio=2)
    if px.isNull():
        return ""
    key = f"{name}-{color.lstrip('#')}-{size}.png"
    path = _asset_dir() / key
    if not path.exists() and not px.save(str(path), "PNG"):
        return ""
    return path.as_posix()
