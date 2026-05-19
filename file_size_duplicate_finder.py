#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                     أداة عزل الملفات المتقاربة بالحجم                        ║
║                      File Size Duplicate Finder                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  تطوير: عبدالكريم العبود                                                    ║
║  البريد: abo.saleh.g@gmail.com                                               ║
║  © 2025 [File Size Duplicate Finder] - All Rights Reserved                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import json
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
import csv

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QDoubleSpinBox, QTreeWidget,
    QTreeWidgetItem, QFileDialog, QProgressBar, QCheckBox,
    QGroupBox, QMessageBox, QMenu, QAction, QStatusBar, QFrame,
    QSplitter, QTabWidget, QTextEdit, QHeaderView, QStyle,
    QStyleFactory, QToolButton, QSizePolicy, QSpacerItem,
    QListWidget, QListWidgetItem, QDialog, QDialogButtonBox,
    QFormLayout, QComboBox
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QSize, QTimer, QSettings,
    QUrl, QPropertyAnimation, QEasingCurve
)
from PyQt5.QtGui import (
    QFont, QIcon, QColor, QPalette, QPixmap, QBrush,
    QLinearGradient, QPainter, QDesktopServices
)

# محاولة استيراد مكتبة الصوت
try:
    from PyQt5.QtMultimedia import QSound, QSoundEffect
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

# محاولة استيراد مكتبة سلة المحذوفات
try:
    from send2trash import send2trash
    TRASH_AVAILABLE = True
except ImportError:
    TRASH_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# الثوابت والإعدادات
# ═══════════════════════════════════════════════════════════════════════════════

APP_NAME = "أداة عزل الملفات المتقاربة بالحجم"
APP_VERSION = "2.0"
DEVELOPER = "عبدالكريم العبود"
EMAIL = "abo.saleh.g@gmail.com"
COPYRIGHT = "© 2025 [File Size Duplicate Finder] - All Rights Reserved"

# ملفات البيانات
CONFIG_FILE = "file_finder_config.json"
HISTORY_FILE = "file_finder_history.json"

# ألوان المجموعات
GROUP_COLORS = [
    "#E3F2FD", "#E8F5E9", "#FFF3E0", "#F3E5F5", "#E0F7FA",
    "#FBE9E7", "#F1F8E9", "#EDE7F6", "#E1F5FE", "#FFF8E1",
    "#E8EAF6", "#FCE4EC", "#E0F2F1", "#EFEBE9", "#ECEFF1"
]

# عتبات تأكيد العمليات الكبيرة
LARGE_OP_FILE_COUNT = 100
LARGE_OP_SIZE_BYTES = 1024 * 1024 * 1024  # 1 GB

# مجلدات يُفترض استثناؤها أثناء المسح المتداخل
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules",
    ".venv", "venv", "env", ".env", "duplicates_sorted",
    ".history_backup", ".file_finder_cache"
}


# ═══════════════════════════════════════════════════════════════════════════════
# أدوات مساعدة عامة
# ═══════════════════════════════════════════════════════════════════════════════

# أوضاع كشف التكرار
DETECT_MODE_SIZE = "size"            # حجم متقارب فقط (الوضع الأصلي)
DETECT_MODE_PARTIAL_HASH = "partial" # نفس الحجم + partial hash (سريع، دقيق)
DETECT_MODE_FULL_HASH = "full"       # تكرار حقيقي 100% (full hash)

HASH_CACHE_FILE = ".file_finder_hash_cache.json"
PARTIAL_HASH_CHUNK = 64 * 1024       # 64KB من بداية ونهاية الملف


def format_bytes(size: int) -> str:
    """تحويل الحجم بالبايت إلى صيغة قابلة للقراءة."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"


def compute_partial_hash(path: str, chunk_size: int = PARTIAL_HASH_CHUNK) -> Optional[str]:
    """حساب hash جزئي من أول وآخر chunk_size بايت — سريع جداً."""
    try:
        size = os.path.getsize(path)
        h = hashlib.md5()
        with open(path, 'rb') as f:
            # البداية
            h.update(f.read(chunk_size))
            # النهاية (إذا كان الملف أكبر من 2×chunk)
            if size > 2 * chunk_size:
                f.seek(-chunk_size, os.SEEK_END)
                h.update(f.read(chunk_size))
        # ضمّ الحجم للـ hash لتمييز الملفات ذات البدايات/النهايات المتطابقة
        h.update(str(size).encode())
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def compute_full_hash(path: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """حساب SHA-256 الكامل عبر streaming لتجنب تحميل ملفات ضخمة في الذاكرة."""
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


class HashCache:
    """تخزين مؤقت لقيم الـ hash مع مفتاح (path, mtime, size) لتجنب إعادة الحساب."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir or os.path.expanduser("~")
        self.path = os.path.join(self.cache_dir, HASH_CACHE_FILE)
        self.data: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f)
        except OSError:
            pass

    def _is_fresh(self, entry: dict, mtime: float, size: int) -> bool:
        return entry.get('mtime') == mtime and entry.get('size') == size

    def get_partial(self, path: str, mtime: float, size: int) -> Optional[str]:
        entry = self.data.get(path)
        if entry and self._is_fresh(entry, mtime, size):
            return entry.get('partial')
        return None

    def get_full(self, path: str, mtime: float, size: int) -> Optional[str]:
        entry = self.data.get(path)
        if entry and self._is_fresh(entry, mtime, size):
            return entry.get('full')
        return None

    def set_partial(self, path: str, mtime: float, size: int, value: str):
        entry = self.data.setdefault(path, {})
        if not self._is_fresh(entry, mtime, size):
            entry.clear()
        entry['mtime'] = mtime
        entry['size'] = size
        entry['partial'] = value

    def set_full(self, path: str, mtime: float, size: int, value: str):
        entry = self.data.setdefault(path, {})
        if not self._is_fresh(entry, mtime, size):
            entry.clear()
        entry['mtime'] = mtime
        entry['size'] = size
        entry['full'] = value


# ═══════════════════════════════════════════════════════════════════════════════
# هياكل البيانات
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MoveOperation:
    """تسجيل عملية نقل"""
    timestamp: str
    source_path: str
    dest_path: str
    file_name: str
    file_size: int
    group_id: int
    operation_id: str


@dataclass
class OperationBatch:
    """دفعة عمليات نقل"""
    operation_id: str
    timestamp: str
    source_folder: str
    dest_folder: str
    total_files: int
    total_size: int
    operations: List[dict]
    restored: bool = False


# ═══════════════════════════════════════════════════════════════════════════════
# خيط البحث
# ═══════════════════════════════════════════════════════════════════════════════

class FileSearchThread(QThread):
    """خيط منفصل للبحث عن الملفات المتقاربة.

    يدعم البحث المتداخل في المجلدات الفرعية، خوارزمية تجميع بنافذة
    منزلقة O(n log n)، واستثناء المجلدات النظامية.
    """
    progress = pyqtSignal(int, str)
    finished_search = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(
        self,
        folder_path: str,
        threshold_mb: float,
        same_ext_only: bool,
        recursive: bool = False,
        exclude_dirs: Optional[set] = None,
        detect_mode: str = DETECT_MODE_SIZE,
    ):
        super().__init__()
        self.folder_path = folder_path
        self.threshold_mb = threshold_mb
        self.same_ext_only = same_ext_only
        self.recursive = recursive
        self.exclude_dirs = exclude_dirs if exclude_dirs is not None else DEFAULT_EXCLUDE_DIRS
        self.detect_mode = detect_mode
        self.is_running = True

    def stop(self):
        self.is_running = False

    def _iter_files(self):
        """مولّد لقراءة الملفات (مسطح أو متداخل) باستخدام os.scandir."""
        if self.recursive:
            stack = [self.folder_path]
            while stack and self.is_running:
                current = stack.pop()
                try:
                    with os.scandir(current) as it:
                        for entry in it:
                            if not self.is_running:
                                return
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    if entry.name not in self.exclude_dirs:
                                        stack.append(entry.path)
                                elif entry.is_file(follow_symlinks=False):
                                    yield entry
                            except OSError:
                                continue
                except (PermissionError, OSError):
                    continue
        else:
            try:
                with os.scandir(self.folder_path) as it:
                    for entry in it:
                        if not self.is_running:
                            return
                        try:
                            if entry.is_file(follow_symlinks=False):
                                yield entry
                        except OSError:
                            continue
            except (PermissionError, OSError):
                return

    def run(self):
        try:
            self.progress.emit(0, "جاري جمع معلومات الملفات...")
            files_info = []
            count = 0
            last_emit = 0

            for entry in self._iter_files():
                if not self.is_running:
                    return
                try:
                    stat = entry.stat(follow_symlinks=False)
                    size = stat.st_size
                    ext = os.path.splitext(entry.name)[1].lower()
                    files_info.append({
                        'path': entry.path,
                        'name': entry.name,
                        'size': size,
                        'ext': ext,
                        'created': datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
                        'modified': datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
                except (OSError, PermissionError):
                    continue

                count += 1
                # إرسال إشارة تقدم كل 200 ملف لتجنب إغراق الواجهة
                if count - last_emit >= 200:
                    self.progress.emit(
                        min(45, count // 50),
                        f"جاري فحص الملفات... ({count} ملف)"
                    )
                    last_emit = count

            if not self.is_running:
                return

            self.progress.emit(50, f"جاري تحليل {len(files_info)} ملف بخوارزمية النافذة المنزلقة...")

            groups = self._group_with_sliding_window(files_info)

            # تنقية المجموعات بالـ hash إذا كان مطلوباً
            if self.detect_mode in (DETECT_MODE_PARTIAL_HASH, DETECT_MODE_FULL_HASH) and groups:
                groups = self._refine_by_hash(groups)

            self.progress.emit(100, f"اكتمل البحث - {len(groups)} مجموعة")
            self.finished_search.emit(groups)

        except Exception as e:
            self.error.emit(str(e))

    def _refine_by_hash(self, groups: List[List[Dict]]) -> List[List[Dict]]:
        """تنقية المجموعات: حساب hash لكل ملف وإعادة التجميع حسب التطابق الفعلي."""
        cache = HashCache()
        total_files = sum(len(g) for g in groups)
        processed = 0
        refined: List[List[Dict]] = []
        use_full = self.detect_mode == DETECT_MODE_FULL_HASH
        label = "SHA-256 كامل" if use_full else "Partial hash"

        for group in groups:
            if not self.is_running:
                cache.save()
                return refined

            # الخطوة الأولى: partial hash لتقسيم المجموعة سريعاً
            buckets_partial: Dict[str, List[Dict]] = {}
            for f in group:
                if not self.is_running:
                    cache.save()
                    return refined
                try:
                    stat = os.stat(f['path'])
                    mtime, size = stat.st_mtime, stat.st_size
                except OSError:
                    processed += 1
                    continue
                ph = cache.get_partial(f['path'], mtime, size)
                if ph is None:
                    ph = compute_partial_hash(f['path'])
                    if ph:
                        cache.set_partial(f['path'], mtime, size, ph)
                if ph:
                    buckets_partial.setdefault(ph, []).append(f)
                processed += 1
                pct = 50 + int(processed / max(total_files, 1) * 50)
                self.progress.emit(pct, f"حساب {label}... ({processed}/{total_files})")

            for bucket in buckets_partial.values():
                if len(bucket) < 2:
                    continue
                if not use_full:
                    refined.append(bucket)
                    continue

                # الخطوة الثانية: full hash للمطابقات في partial
                buckets_full: Dict[str, List[Dict]] = {}
                for f in bucket:
                    if not self.is_running:
                        cache.save()
                        return refined
                    try:
                        stat = os.stat(f['path'])
                        mtime, size = stat.st_mtime, stat.st_size
                    except OSError:
                        continue
                    fh = cache.get_full(f['path'], mtime, size)
                    if fh is None:
                        fh = compute_full_hash(f['path'])
                        if fh:
                            cache.set_full(f['path'], mtime, size, fh)
                    if fh:
                        buckets_full.setdefault(fh, []).append(f)
                for sub in buckets_full.values():
                    if len(sub) > 1:
                        refined.append(sub)

        cache.save()
        return refined

    def _group_with_sliding_window(self, files_info: List[Dict]) -> List[List[Dict]]:
        """تجميع الملفات المتقاربة بالحجم باستخدام نافذة منزلقة O(n log n).

        خوارزمية: بعد فرز الملفات بالحجم، نمسح كل ملف مرة واحدة ونضمّه
        إلى المجموعة الحالية إذا كان الفرق ≤ threshold عن أول ملف في المجموعة.
        """
        if not files_info:
            return []

        threshold_bytes = int(self.threshold_mb * 1024 * 1024)
        files_info.sort(key=lambda x: x['size'])

        groups: List[List[Dict]] = []
        current: List[Dict] = [files_info[0]]
        anchor_size = files_info[0]['size']

        for f in files_info[1:]:
            if not self.is_running:
                return groups
            if f['size'] - anchor_size <= threshold_bytes:
                current.append(f)
            else:
                if len(current) > 1:
                    groups.extend(self._split_by_extension(current))
                current = [f]
                anchor_size = f['size']

        if len(current) > 1:
            groups.extend(self._split_by_extension(current))

        return groups

    def _split_by_extension(self, group: List[Dict]) -> List[List[Dict]]:
        """عند تفعيل خيار "نفس الامتداد فقط"، نفصل المجموعة حسب الامتداد."""
        if not self.same_ext_only:
            return [group]
        by_ext: Dict[str, List[Dict]] = {}
        for f in group:
            by_ext.setdefault(f['ext'], []).append(f)
        return [files for files in by_ext.values() if len(files) > 1]


# ═══════════════════════════════════════════════════════════════════════════════
# خيط النقل
# ═══════════════════════════════════════════════════════════════════════════════

class FileMoveThread(QThread):
    """خيط منفصل لنقل الملفات"""
    progress = pyqtSignal(int, str)
    finished_move = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, selected_files: List[Dict], base_folder: str, operation_id: str):
        super().__init__()
        self.selected_files = selected_files
        self.base_folder = base_folder
        self.operation_id = operation_id
        self.is_running = True
    
    def stop(self):
        self.is_running = False
    
    def run(self):
        try:
            output_folder = os.path.join(self.base_folder, "duplicates_sorted")
            os.makedirs(output_folder, exist_ok=True)
            
            operations = []
            moved_count = 0
            error_files = []
            total_size = 0
            
            total_files = sum(len(group) for group in self.selected_files)
            current_file = 0
            
            for group_idx, group_files in enumerate(self.selected_files, 1):
                if not self.is_running:
                    return
                
                group_folder = os.path.join(output_folder, f"folder_{group_idx}")
                os.makedirs(group_folder, exist_ok=True)
                
                for file_info in group_files:
                    if not self.is_running:
                        return
                    
                    current_file += 1
                    filepath = file_info['path']
                    
                    try:
                        if os.path.exists(filepath) and os.path.isfile(filepath):
                            filename = os.path.basename(filepath)
                            dest_path = os.path.join(group_folder, filename)
                            
                            # التعامل مع الأسماء المكررة
                            counter = 1
                            base_name, ext = os.path.splitext(filename)
                            while os.path.exists(dest_path):
                                filename = f"{base_name}_{counter}{ext}"
                                dest_path = os.path.join(group_folder, filename)
                                counter += 1
                            
                            file_size = os.path.getsize(filepath)
                            shutil.move(filepath, dest_path)
                            
                            operations.append({
                                'source': filepath,
                                'dest': dest_path,
                                'name': file_info['name'],
                                'size': file_size,
                                'group': group_idx
                            })
                            
                            moved_count += 1
                            total_size += file_size
                        else:
                            error_files.append(file_info['name'])
                    except Exception as e:
                        error_files.append(f"{file_info['name']} ({str(e)})")
                    
                    progress = int(current_file / total_files * 100)
                    self.progress.emit(progress, f"جاري النقل... ({current_file}/{total_files})")
            
            result = {
                'operation_id': self.operation_id,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'source_folder': self.base_folder,
                'dest_folder': output_folder,
                'operations': operations,
                'moved_count': moved_count,
                'error_files': error_files,
                'total_size': total_size
            }
            
            self.finished_move.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# خيط الإرجاع
# ═══════════════════════════════════════════════════════════════════════════════

class FileRestoreThread(QThread):
    """خيط منفصل لإرجاع الملفات"""
    progress = pyqtSignal(int, str)
    finished_restore = pyqtSignal(dict)
    error = pyqtSignal(str)
    
    def __init__(self, batch: dict):
        super().__init__()
        self.batch = batch
        self.is_running = True
    
    def stop(self):
        self.is_running = False
    
    def run(self):
        try:
            operations = self.batch['operations']
            total = len(operations)
            restored_count = 0
            error_files = []
            
            for idx, op in enumerate(operations):
                if not self.is_running:
                    return
                
                try:
                    if os.path.exists(op['dest']):
                        # التأكد من وجود المجلد المصدر
                        source_dir = os.path.dirname(op['source'])
                        os.makedirs(source_dir, exist_ok=True)
                        
                        # التعامل مع الملفات الموجودة
                        dest_path = op['source']
                        if os.path.exists(dest_path):
                            base, ext = os.path.splitext(dest_path)
                            counter = 1
                            while os.path.exists(dest_path):
                                dest_path = f"{base}_restored_{counter}{ext}"
                                counter += 1
                        
                        shutil.move(op['dest'], dest_path)
                        restored_count += 1
                    else:
                        error_files.append(op['name'])
                except Exception as e:
                    error_files.append(f"{op['name']} ({str(e)})")
                
                progress = int((idx + 1) / total * 100)
                self.progress.emit(progress, f"جاري الإرجاع... ({idx + 1}/{total})")
            
            # حذف المجلدات الفارغة
            try:
                dest_folder = self.batch['dest_folder']
                if os.path.exists(dest_folder):
                    for item in os.listdir(dest_folder):
                        item_path = os.path.join(dest_folder, item)
                        if os.path.isdir(item_path) and not os.listdir(item_path):
                            os.rmdir(item_path)
                    if not os.listdir(dest_folder):
                        os.rmdir(dest_folder)
            except:
                pass
            
            result = {
                'restored_count': restored_count,
                'error_files': error_files,
                'operation_id': self.batch['operation_id']
            }
            
            self.finished_restore.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# نافذة سجل العمليات
# ═══════════════════════════════════════════════════════════════════════════════

class HistoryDialog(QDialog):
    """نافذة عرض سجل العمليات"""
    
    restore_requested = pyqtSignal(dict)
    
    def __init__(self, history: List[dict], parent=None):
        super().__init__(parent)
        self.history = history
        self.setWindowTitle("📋 سجل العمليات")
        self.setMinimumSize(700, 500)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # قائمة العمليات
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.itemSelectionChanged.connect(self.on_selection_changed)
        
        for batch in reversed(self.history):
            status = "✅ تم الإرجاع" if batch.get('restored', False) else "📦 قابل للإرجاع"
            item_text = (
                f"{batch['timestamp']} | "
                f"{batch['total_files']} ملف | "
                f"{self.format_size(batch['total_size'])} | "
                f"{status}"
            )
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, batch)
            if batch.get('restored', False):
                item.setForeground(QColor("#888888"))
            self.list_widget.addItem(item)
        
        layout.addWidget(self.list_widget)
        
        # تفاصيل العملية
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(150)
        layout.addWidget(self.details_text)
        
        # الأزرار
        buttons_layout = QHBoxLayout()
        
        self.restore_btn = QPushButton("🔄 إرجاع الملفات")
        self.restore_btn.setEnabled(False)
        self.restore_btn.clicked.connect(self.on_restore_clicked)
        self.restore_btn.setStyleSheet("""
            QPushButton {
                background-color: #27ae60;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #1e8449; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        
        close_btn = QPushButton("إغلاق")
        close_btn.clicked.connect(self.close)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #95a5a6;
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #7f8c8d; }
        """)
        
        buttons_layout.addWidget(self.restore_btn)
        buttons_layout.addStretch()
        buttons_layout.addWidget(close_btn)
        layout.addLayout(buttons_layout)
    
    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"
    
    def on_selection_changed(self):
        items = self.list_widget.selectedItems()
        if items:
            batch = items[0].data(Qt.UserRole)
            
            details = f"""📅 التاريخ: {batch['timestamp']}
📁 المجلد المصدر: {batch['source_folder']}
📂 مجلد الوجهة: {batch['dest_folder']}
📊 عدد الملفات: {batch['total_files']}
💾 الحجم الكلي: {self.format_size(batch['total_size'])}
🔑 معرف العملية: {batch['operation_id']}
"""
            self.details_text.setText(details)
            self.restore_btn.setEnabled(not batch.get('restored', False))
        else:
            self.details_text.clear()
            self.restore_btn.setEnabled(False)
    
    def on_restore_clicked(self):
        items = self.list_widget.selectedItems()
        if items:
            batch = items[0].data(Qt.UserRole)
            reply = QMessageBox.question(
                self, "تأكيد الإرجاع",
                f"هل تريد إرجاع {batch['total_files']} ملف إلى مواقعها الأصلية؟",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.restore_requested.emit(batch)
                self.close()


# ═══════════════════════════════════════════════════════════════════════════════
# نافذة المعاينة (Dry-run)
# ═══════════════════════════════════════════════════════════════════════════════

class DryRunDialog(QDialog):
    """نافذة معاينة العملية قبل التنفيذ — تعرض جدولاً تفصيلياً للملفات."""

    def __init__(self, selected_groups: List[List[Dict]], action_label: str, parent=None):
        super().__init__(parent)
        self.selected_groups = selected_groups
        self.confirmed = False
        self.setWindowTitle(f"📋 معاينة العملية — {action_label}")
        self.setMinimumSize(820, 540)
        self.setLayoutDirection(Qt.RightToLeft)
        self._build_ui(action_label)

    def _build_ui(self, action_label: str):
        layout = QVBoxLayout(self)

        total_files = sum(len(g) for g in self.selected_groups)
        total_size = sum(f['size'] for g in self.selected_groups for f in g)

        # ملخص في الأعلى
        summary = QLabel(
            f"<div style='font-size:14px; padding:10px;'>"
            f"🔹 <b>الإجراء:</b> {action_label}<br>"
            f"🔹 <b>عدد المجموعات:</b> {len(self.selected_groups)}<br>"
            f"🔹 <b>إجمالي الملفات:</b> {total_files}<br>"
            f"🔹 <b>الحجم الكلي:</b> {format_bytes(total_size)}"
            f"</div>"
        )
        summary.setStyleSheet(
            "background-color:#E3F2FD; border-radius:8px; border:1px solid #90CAF9;"
        )
        layout.addWidget(summary)

        # تحذير للعمليات الكبيرة
        if total_files >= LARGE_OP_FILE_COUNT or total_size >= LARGE_OP_SIZE_BYTES:
            warn = QLabel(
                "⚠️ <b>تنبيه:</b> هذه عملية كبيرة — يُنصح بمراجعة القائمة بعناية قبل المتابعة."
            )
            warn.setStyleSheet(
                "color:#BF360C; background-color:#FFF3E0; padding:8px; "
                "border-radius:6px; border:1px solid #FFAB91;"
            )
            layout.addWidget(warn)

        # جدول الملفات
        tree = QTreeWidget()
        tree.setHeaderLabels(["الاسم", "الحجم", "الامتداد", "المسار"])
        tree.setAlternatingRowColors(True)
        for idx, group in enumerate(self.selected_groups, 1):
            grp_item = QTreeWidgetItem([
                f"📁 المجموعة {idx} ({len(group)} ملف)",
                format_bytes(sum(f['size'] for f in group)),
                "", ""
            ])
            for f in group:
                child = QTreeWidgetItem([
                    f['name'],
                    format_bytes(f['size']),
                    f.get('ext', ''),
                    f['path'],
                ])
                grp_item.addChild(child)
            grp_item.setExpanded(False)
            tree.addTopLevelItem(grp_item)
        tree.resizeColumnToContents(0)
        layout.addWidget(tree, 1)

        # أزرار
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("❌ إلغاء")
        cancel_btn.clicked.connect(self.reject)
        confirm_btn = QPushButton(f"✅ تأكيد — {action_label}")
        confirm_btn.setStyleSheet(
            "QPushButton { background-color:#2E7D32; color:white; "
            "padding:8px 18px; border-radius:6px; font-weight:bold; }"
            "QPushButton:hover { background-color:#1B5E20; }"
        )
        confirm_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

    def _on_confirm(self):
        self.confirmed = True
        self.accept()


# ═══════════════════════════════════════════════════════════════════════════════
# خيط الحذف إلى سلة المحذوفات
# ═══════════════════════════════════════════════════════════════════════════════

class FileTrashThread(QThread):
    """خيط منفصل لإرسال الملفات إلى سلة المحذوفات."""
    progress = pyqtSignal(int, str)
    finished_trash = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, selected_files: List[List[Dict]]):
        super().__init__()
        self.selected_files = selected_files
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        if not TRASH_AVAILABLE:
            self.error.emit("مكتبة send2trash غير متوفرة")
            return
        try:
            total = sum(len(g) for g in self.selected_files)
            trashed = 0
            failed = []
            total_size = 0
            done = 0

            for group in self.selected_files:
                for finfo in group:
                    if not self.is_running:
                        return
                    done += 1
                    path = finfo['path']
                    try:
                        size = os.path.getsize(path) if os.path.exists(path) else 0
                        send2trash(path)
                        trashed += 1
                        total_size += size
                    except Exception as e:
                        failed.append(f"{finfo['name']} ({e})")
                    pct = int(done / total * 100) if total else 100
                    self.progress.emit(pct, f"إرسال إلى السلة... ({done}/{total})")

            self.finished_trash.emit({
                'trashed_count': trashed,
                'total_size': total_size,
                'failed': failed,
            })
        except Exception as e:
            self.error.emit(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# النافذة الرئيسية
# ═══════════════════════════════════════════════════════════════════════════════

class FileSizeDuplicateFinder(QMainWindow):
    """النافذة الرئيسية للتطبيق"""
    
    def __init__(self):
        super().__init__()
        
        # المتغيرات
        self.similar_groups = []
        self.file_paths = {}
        self.search_thread = None
        self.move_thread = None
        self.restore_thread = None
        self.history = []
        self.settings = QSettings("FileSizeDuplicateFinder", "Settings")
        
        # تحميل السجل
        self.load_history()
        
        # إعداد الواجهة
        self.init_ui()
        
        # تحميل الإعدادات
        self.load_settings()
    
    def init_ui(self):
        """تهيئة واجهة المستخدم"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setWindowIcon(_load_app_icon())
        self.setMinimumSize(1000, 750)
        self.setLayoutDirection(Qt.RightToLeft)
        
        # تطبيق النمط
        self.apply_style()
        
        # الودجت المركزي
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # العنوان
        title_frame = self.create_title_frame()
        main_layout.addWidget(title_frame)
        
        # التبويبات
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #3498db;
                border-radius: 5px;
                background: white;
            }
            QTabBar::tab {
                background: #ecf0f1;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
            QTabBar::tab:selected {
                background: #3498db;
                color: white;
            }
        """)
        
        # تبويب البحث
        search_tab = self.create_search_tab()
        self.tab_widget.addTab(search_tab, "🔍 البحث والعزل")
        
        # تبويب السجل
        log_tab = self.create_log_tab()
        self.tab_widget.addTab(log_tab, "📋 سجل العمليات")
        
        main_layout.addWidget(self.tab_widget)
        
        # شريط الحالة
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("جاهز للعمل")
        
        # حقوق الملكية
        copyright_label = QLabel(f"تطوير: {DEVELOPER} | {EMAIL} | {COPYRIGHT}")
        copyright_label.setAlignment(Qt.AlignCenter)
        copyright_label.setStyleSheet("color: #666; font-size: 11px; padding: 5px;")
        main_layout.addWidget(copyright_label)
    
    def apply_style(self):
        """تطبيق النمط العام"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f6fa;
            }
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 2px solid #3498db;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                background-color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top right;
                padding: 5px 15px;
                background-color: #3498db;
                color: white;
                border-radius: 5px;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #1c5980;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
            QLineEdit, QDoubleSpinBox {
                padding: 8px;
                border: 2px solid #ddd;
                border-radius: 5px;
                background-color: white;
                font-size: 12px;
            }
            QLineEdit:focus, QDoubleSpinBox:focus {
                border-color: #3498db;
            }
            QTreeWidget {
                border: 2px solid #ddd;
                border-radius: 5px;
                background-color: white;
                font-size: 12px;
                alternate-background-color: #f8f9fa;
            }
            QTreeWidget::item {
                padding: 5px;
                border-bottom: 1px solid #eee;
            }
            QTreeWidget::item:selected {
                background-color: #3498db;
                color: white;
            }
            QHeaderView::section {
                background-color: #3498db;
                color: white;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
            QProgressBar {
                border: 2px solid #ddd;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
                background-color: #ecf0f1;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #27ae60, stop:1 #2ecc71);
                border-radius: 3px;
            }
            QCheckBox {
                font-size: 12px;
                spacing: 8px;
            }
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 5px;
                background-color: #fafafa;
            }
        """)
    
    def create_title_frame(self):
        """إنشاء إطار العنوان"""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                border-radius: 10px;
                padding: 15px;
            }
        """)
        layout = QVBoxLayout(frame)
        
        title = QLabel(f"🔍 {APP_NAME}")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: white; font-size: 24px; font-weight: bold;")
        layout.addWidget(title)
        
        subtitle = QLabel("ابحث عن الملفات المتقاربة في الحجم وقم بعزلها في مجموعات منظمة")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #ecf0f1; font-size: 13px;")
        layout.addWidget(subtitle)
        
        return frame
    
    def create_search_tab(self):
        """إنشاء تبويب البحث"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # إعدادات البحث
        settings_group = QGroupBox("إعدادات البحث")
        settings_layout = QVBoxLayout(settings_group)
        
        # صف اختيار المجلد
        folder_layout = QHBoxLayout()
        folder_label = QLabel("📁 المجلد:")
        folder_label.setMinimumWidth(80)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("اختر المجلد للبحث فيه...")
        self.folder_input.setReadOnly(True)
        browse_btn = QPushButton("استعراض 📂")
        browse_btn.clicked.connect(self.browse_folder)
        folder_layout.addWidget(folder_label)
        folder_layout.addWidget(self.folder_input, 1)
        folder_layout.addWidget(browse_btn)
        settings_layout.addLayout(folder_layout)
        
        # صف الإعدادات
        options_layout = QHBoxLayout()
        
        threshold_label = QLabel("📏 حد التقارب (ميجابايت):")
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.1, 1000)
        self.threshold_spin.setValue(3.0)
        self.threshold_spin.setSingleStep(0.5)
        options_layout.addWidget(threshold_label)
        options_layout.addWidget(self.threshold_spin)
        
        options_layout.addSpacing(30)
        
        self.same_ext_check = QCheckBox("🏷️ نفس الامتداد فقط")
        self.same_ext_check.setToolTip("البحث فقط في الملفات التي لها نفس الامتداد")
        options_layout.addWidget(self.same_ext_check)

        options_layout.addSpacing(15)

        self.recursive_check = QCheckBox("🌳 المجلدات الفرعية")
        self.recursive_check.setToolTip(
            "البحث المتداخل في كل المجلدات الفرعية (يتجاهل المجلدات النظامية مثل .git و node_modules)"
        )
        options_layout.addWidget(self.recursive_check)

        options_layout.addSpacing(15)

        options_layout.addWidget(QLabel("🔍 وضع الكشف:"))
        self.detect_mode_combo = QComboBox()
        self.detect_mode_combo.addItem("حجم متقارب (سريع)", DETECT_MODE_SIZE)
        self.detect_mode_combo.addItem("Partial hash (متوازن)", DETECT_MODE_PARTIAL_HASH)
        self.detect_mode_combo.addItem("تكرار حقيقي SHA-256 (دقيق)", DETECT_MODE_FULL_HASH)
        self.detect_mode_combo.setToolTip(
            "حجم متقارب: مقارنة الأحجام فقط.\n"
            "Partial hash: نفس الحجم + توقيع من بداية ونهاية الملف.\n"
            "تكرار حقيقي: SHA-256 كامل — أبطأ لكن مضمون."
        )
        options_layout.addWidget(self.detect_mode_combo)

        options_layout.addStretch()
        settings_layout.addLayout(options_layout)
        
        layout.addWidget(settings_group)
        
        # أزرار التحكم
        control_layout = QHBoxLayout()
        
        self.search_btn = QPushButton("🔍 بدء البحث")
        self.search_btn.clicked.connect(self.start_search)
        self.search_btn.setMinimumHeight(45)
        self.search_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #667eea, stop:1 #764ba2);
                font-size: 14px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5a6fd6, stop:1 #6a4190);
            }
        """)
        
        self.stop_btn = QPushButton("⏹ إيقاف")
        self.stop_btn.clicked.connect(self.stop_search)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton { background-color: #e74c3c; }
            QPushButton:hover { background-color: #c0392b; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        
        self.move_btn = QPushButton("📦 عزل المحدد")
        self.move_btn.clicked.connect(self.move_files)
        self.move_btn.setEnabled(False)
        self.move_btn.setToolTip("عرض معاينة قبل النقل إلى مجلد منظم")
        self.move_btn.setStyleSheet("""
            QPushButton { background-color: #27ae60; }
            QPushButton:hover { background-color: #1e8449; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)

        self.trash_btn = QPushButton("🗑️ سلة المحذوفات")
        self.trash_btn.clicked.connect(self.move_to_trash)
        self.trash_btn.setEnabled(False)
        if not TRASH_AVAILABLE:
            self.trash_btn.setToolTip("غير متوفر — ثبّت send2trash")
        else:
            self.trash_btn.setToolTip("إرسال الملفات المحددة إلى سلة محذوفات النظام (قابلة للاسترداد)")
        self.trash_btn.setStyleSheet("""
            QPushButton { background-color: #c0392b; }
            QPushButton:hover { background-color: #962d22; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)

        self.restore_btn = QPushButton("🔄 إرجاع الملفات")
        self.restore_btn.clicked.connect(self.show_history_dialog)
        self.restore_btn.setStyleSheet("""
            QPushButton { background-color: #f39c12; }
            QPushButton:hover { background-color: #d68910; }
        """)

        control_layout.addWidget(self.search_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.move_btn)
        control_layout.addWidget(self.trash_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.restore_btn)
        
        layout.addLayout(control_layout)
        
        # شريط التقدم
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(25)
        self.progress_label = QLabel("")
        self.progress_label.setMinimumWidth(200)
        progress_layout.addWidget(self.progress_bar, 1)
        progress_layout.addWidget(self.progress_label)
        layout.addLayout(progress_layout)
        
        # النتائج والمعاينة
        splitter = QSplitter(Qt.Vertical)
        
        # جدول النتائج
        results_group = QGroupBox("النتائج")
        results_layout = QVBoxLayout(results_group)
        
        # إحصائيات
        self.stats_label = QLabel("📊 لم يتم البحث بعد")
        self.stats_label.setStyleSheet("""
            background-color: #e8f4fc;
            padding: 10px;
            border-radius: 5px;
            font-weight: bold;
            color: #2c3e50;
        """)
        results_layout.addWidget(self.stats_label)
        
        # شجرة النتائج
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels(["", "المجموعة", "اسم الملف", "الحجم", "الامتداد"])
        self.results_tree.setAlternatingRowColors(True)
        self.results_tree.itemClicked.connect(self.on_item_clicked)
        self.results_tree.itemDoubleClicked.connect(self.open_file_location)
        self.results_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results_tree.customContextMenuRequested.connect(self.show_context_menu)
        
        header = self.results_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.results_tree.setColumnWidth(0, 40)
        
        results_layout.addWidget(self.results_tree)
        
        # أزرار التحديد
        select_layout = QHBoxLayout()
        
        select_all_btn = QPushButton("☑ تحديد الكل")
        select_all_btn.clicked.connect(self.select_all)
        select_all_btn.setStyleSheet("background-color: #9b59b6;")
        
        deselect_all_btn = QPushButton("☐ إلغاء التحديد")
        deselect_all_btn.clicked.connect(self.deselect_all)
        deselect_all_btn.setStyleSheet("background-color: #95a5a6;")
        
        export_btn = QPushButton("💾 تصدير التقرير")
        export_btn.clicked.connect(self.export_report)
        export_btn.setStyleSheet("background-color: #1abc9c;")
        
        select_layout.addWidget(select_all_btn)
        select_layout.addWidget(deselect_all_btn)
        select_layout.addStretch()
        select_layout.addWidget(export_btn)
        
        results_layout.addLayout(select_layout)
        splitter.addWidget(results_group)
        
        # معاينة الملف
        preview_group = QGroupBox("معاينة الملف")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(120)
        self.preview_text.setPlaceholderText("اضغط على ملف لعرض تفاصيله...")
        preview_layout.addWidget(self.preview_text)
        
        splitter.addWidget(preview_group)
        splitter.setSizes([500, 150])
        
        layout.addWidget(splitter, 1)
        
        return widget
    
    def create_log_tab(self):
        """إنشاء تبويب السجل"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # سجل العمليات
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                background-color: #1e1e1e;
                color: #d4d4d4;
                border-radius: 5px;
            }
        """)
        
        layout.addWidget(self.log_text)
        
        # أزرار السجل
        log_buttons = QHBoxLayout()
        
        clear_log_btn = QPushButton("🗑 مسح السجل")
        clear_log_btn.clicked.connect(self.clear_log)
        clear_log_btn.setStyleSheet("background-color: #e74c3c;")
        
        save_log_btn = QPushButton("💾 حفظ السجل")
        save_log_btn.clicked.connect(self.save_log)
        save_log_btn.setStyleSheet("background-color: #27ae60;")
        
        log_buttons.addStretch()
        log_buttons.addWidget(save_log_btn)
        log_buttons.addWidget(clear_log_btn)
        
        layout.addLayout(log_buttons)
        
        return widget
    
    def log_message(self, message: str, level: str = "INFO"):
        """إضافة رسالة للسجل"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "#58a6ff",
            "SUCCESS": "#3fb950",
            "WARNING": "#d29922",
            "ERROR": "#f85149"
        }
        color = colors.get(level, "#d4d4d4")
        
        html = f'<span style="color: #888;">[{timestamp}]</span> '
        html += f'<span style="color: {color};">[{level}]</span> '
        html += f'<span style="color: #d4d4d4;">{message}</span><br>'
        
        self.log_text.insertHtml(html)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )
    
    def browse_folder(self):
        """اختيار مجلد"""
        last_folder = self.settings.value("last_folder", "")
        folder = QFileDialog.getExistingDirectory(
            self, "اختر المجلد", last_folder,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if folder:
            self.folder_input.setText(folder)
            self.settings.setValue("last_folder", folder)
            self.log_message(f"تم اختيار المجلد: {folder}")
    
    def start_search(self):
        """بدء البحث"""
        folder = self.folder_input.text()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "تنبيه", "الرجاء اختيار مجلد صالح")
            return
        
        self.results_tree.clear()
        self.similar_groups = []
        self.file_paths = {}
        self.progress_bar.setValue(0)
        
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.move_btn.setEnabled(False)
        
        self.log_message("بدء البحث عن الملفات المتقاربة...")
        
        self.search_thread = FileSearchThread(
            folder,
            self.threshold_spin.value(),
            self.same_ext_check.isChecked(),
            recursive=self.recursive_check.isChecked(),
            detect_mode=self.detect_mode_combo.currentData() or DETECT_MODE_SIZE,
        )
        self.search_thread.progress.connect(self.on_search_progress)
        self.search_thread.finished_search.connect(self.on_search_finished)
        self.search_thread.error.connect(self.on_search_error)
        self.search_thread.start()
    
    def stop_search(self):
        """إيقاف البحث"""
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.stop()
            self.search_thread.wait()
            self.log_message("تم إيقاف البحث", "WARNING")
        
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def on_search_progress(self, value: int, message: str):
        """تحديث التقدم"""
        self.progress_bar.setValue(value)
        self.progress_label.setText(message)
        self.status_bar.showMessage(message)
    
    def on_search_finished(self, groups: list):
        """انتهاء البحث"""
        self.similar_groups = groups
        self.display_results(groups)
        
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        has_groups = len(groups) > 0
        self.move_btn.setEnabled(has_groups)
        if hasattr(self, 'trash_btn'):
            self.trash_btn.setEnabled(has_groups and TRASH_AVAILABLE)
        
        # تشغيل صوت الإشعار
        self.play_notification()
        
        self.log_message(f"اكتمل البحث - تم العثور على {len(groups)} مجموعة", "SUCCESS")
    
    def on_search_error(self, error: str):
        """خطأ في البحث"""
        QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء البحث:\n{error}")
        self.log_message(f"خطأ: {error}", "ERROR")
        
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
    
    def display_results(self, groups: list):
        """عرض النتائج"""
        self.results_tree.clear()
        
        total_files = 0
        total_size = 0
        potential_savings = 0
        
        for group_idx, group_files in enumerate(groups):
            color = GROUP_COLORS[group_idx % len(GROUP_COLORS)]
            
            # إنشاء عنصر المجموعة
            group_item = QTreeWidgetItem(self.results_tree)
            group_item.setText(0, "☐")
            group_item.setText(1, f"المجموعة {group_idx + 1}")
            group_size = sum(f['size'] for f in group_files)
            group_item.setText(3, f"{len(group_files)} ملفات - {self.format_size(group_size)}")
            
            for col in range(5):
                group_item.setBackground(col, QColor(color))
            
            group_item.setExpanded(True)
            group_item.setData(0, Qt.UserRole, {'type': 'group', 'index': group_idx})
            
            # حساب التوفير المحتمل (جميع الملفات عدا الأكبر)
            sorted_files = sorted(group_files, key=lambda x: x['size'], reverse=True)
            potential_savings += sum(f['size'] for f in sorted_files[1:])
            
            for file_info in group_files:
                file_item = QTreeWidgetItem(group_item)
                file_item.setText(0, "☐")
                file_item.setText(2, file_info['name'])
                file_item.setText(3, self.format_size(file_info['size']))
                file_item.setText(4, file_info['ext'] or "بدون")
                
                file_id = f"file_{group_idx}_{file_info['name']}"
                self.file_paths[file_id] = file_info
                file_item.setData(0, Qt.UserRole, {'type': 'file', 'id': file_id, 'info': file_info})
                
                total_files += 1
                total_size += file_info['size']
        
        # تحديث الإحصائيات
        stats_text = (
            f"📊 الإحصائيات: {len(groups)} مجموعة | "
            f"{total_files} ملف | "
            f"الحجم الكلي: {self.format_size(total_size)} | "
            f"💰 التوفير المحتمل: {self.format_size(potential_savings)}"
        )
        self.stats_label.setText(stats_text)
    
    def format_size(self, size: int) -> str:
        """تنسيق الحجم"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} TB"
    
    def on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """معالجة النقر"""
        if column == 0:
            # تبديل التحديد
            current = item.text(0)
            new_state = "☑" if current == "☐" else "☐"
            item.setText(0, new_state)
            
            # إذا كان مجموعة، حدث الأطفال
            for i in range(item.childCount()):
                item.child(i).setText(0, new_state)
            
            # إذا كان ملف، تحقق من حالة المجموعة
            parent = item.parent()
            if parent:
                all_checked = all(
                    parent.child(i).text(0) == "☑"
                    for i in range(parent.childCount())
                )
                parent.setText(0, "☑" if all_checked else "☐")
        
        # عرض المعاينة
        data = item.data(0, Qt.UserRole)
        if data and data.get('type') == 'file':
            info = data['info']
            preview = f"""📄 اسم الملف: {info['name']}
📏 الحجم: {self.format_size(info['size'])}
🏷️ الامتداد: {info['ext'] or 'بدون'}
📅 تاريخ الإنشاء: {info['created']}
📝 آخر تعديل: {info['modified']}
📁 المسار: {info['path']}"""
            self.preview_text.setText(preview)
    
    def open_file_location(self, item: QTreeWidgetItem, column: int):
        """فتح موقع الملف"""
        data = item.data(0, Qt.UserRole)
        if data and data.get('type') == 'file':
            folder = os.path.dirname(data['info']['path'])
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self.log_message(f"فتح المجلد: {folder}")
    
    def show_context_menu(self, position):
        """القائمة السياقية"""
        item = self.results_tree.itemAt(position)
        if not item:
            return
        
        data = item.data(0, Qt.UserRole)
        if not data or data.get('type') != 'file':
            return
        
        menu = QMenu(self)
        
        open_action = QAction("📂 فتح موقع الملف", self)
        open_action.triggered.connect(lambda: self.open_file_location(item, 0))
        menu.addAction(open_action)
        
        select_action = QAction("☑ تحديد", self)
        select_action.triggered.connect(lambda: item.setText(0, "☑"))
        menu.addAction(select_action)
        
        menu.exec_(self.results_tree.viewport().mapToGlobal(position))
    
    def select_all(self):
        """تحديد الكل"""
        root = self.results_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            group.setText(0, "☑")
            for j in range(group.childCount()):
                group.child(j).setText(0, "☑")
    
    def deselect_all(self):
        """إلغاء التحديد"""
        root = self.results_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            group.setText(0, "☐")
            for j in range(group.childCount()):
                group.child(j).setText(0, "☐")
    
    def get_selected_files(self) -> List[List[Dict]]:
        """الحصول على الملفات المحددة"""
        selected_groups = []
        root = self.results_tree.invisibleRootItem()
        
        for i in range(root.childCount()):
            group = root.child(i)
            group_files = []
            
            for j in range(group.childCount()):
                file_item = group.child(j)
                if file_item.text(0) == "☑":
                    data = file_item.data(0, Qt.UserRole)
                    if data and data.get('info'):
                        group_files.append(data['info'])
            
            if group_files:
                selected_groups.append(group_files)
        
        return selected_groups
    
    def move_files(self):
        """نقل الملفات بعد عرض نافذة المعاينة (Dry-run)."""
        selected = self.get_selected_files()

        if not selected:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد الملفات المراد عزلها")
            return

        # عرض نافذة المعاينة قبل التنفيذ
        dlg = DryRunDialog(selected, "عزل إلى مجلدات", self)
        dlg.exec_()
        if not dlg.confirmed:
            self.log_message("تم إلغاء العملية من نافذة المعاينة")
            return

        total_files = sum(len(g) for g in selected)
        operation_id = hashlib.md5(
            f"{datetime.now().isoformat()}_{total_files}".encode()
        ).hexdigest()[:12]

        self.move_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        if hasattr(self, 'trash_btn'):
            self.trash_btn.setEnabled(False)

        self.log_message(f"بدء عملية النقل - {total_files} ملف...")

        self.move_thread = FileMoveThread(
            selected,
            self.folder_input.text(),
            operation_id
        )
        self.move_thread.progress.connect(self.on_search_progress)
        self.move_thread.finished_move.connect(self.on_move_finished)
        self.move_thread.error.connect(self.on_move_error)
        self.move_thread.start()

    def move_to_trash(self):
        """إرسال الملفات المحددة إلى سلة محذوفات النظام."""
        if not TRASH_AVAILABLE:
            QMessageBox.critical(
                self, "غير متوفر",
                "مكتبة send2trash غير مثبتة.\nنفّذ: pip install send2trash"
            )
            return

        selected = self.get_selected_files()
        if not selected:
            QMessageBox.warning(self, "تنبيه", "الرجاء تحديد الملفات أولاً")
            return

        dlg = DryRunDialog(selected, "إرسال إلى سلة المحذوفات", self)
        dlg.exec_()
        if not dlg.confirmed:
            self.log_message("تم إلغاء عملية الحذف من نافذة المعاينة")
            return

        total_files = sum(len(g) for g in selected)
        self.log_message(f"بدء إرسال {total_files} ملف إلى سلة المحذوفات...")

        self.move_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        if hasattr(self, 'trash_btn'):
            self.trash_btn.setEnabled(False)

        self.trash_thread = FileTrashThread(selected)
        self.trash_thread.progress.connect(self.on_search_progress)
        self.trash_thread.finished_trash.connect(self.on_trash_finished)
        self.trash_thread.error.connect(self.on_move_error)
        self.trash_thread.start()

    def on_trash_finished(self, result: dict):
        """انتهاء عملية الإرسال إلى السلة."""
        self.move_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        if hasattr(self, 'trash_btn'):
            self.trash_btn.setEnabled(True)

        count = result['trashed_count']
        size = result['total_size']
        failed = result.get('failed', [])

        self.log_message(
            f"✅ تم إرسال {count} ملف إلى السلة (حجم إجمالي: {format_bytes(size)})",
            "SUCCESS"
        )
        if failed:
            self.log_message(f"⚠️ فشل في {len(failed)} ملف", "WARNING")

        QMessageBox.information(
            self, "اكتملت العملية",
            f"تم إرسال {count} ملف إلى سلة المحذوفات.\n"
            f"يمكنك استرداد الملفات من سلة محذوفات النظام."
        )
        # إعادة البحث لتحديث القائمة
        if self.folder_input.text():
            self.start_search()
    
    def on_move_finished(self, result: dict):
        """انتهاء النقل"""
        # حفظ في السجل
        batch = {
            'operation_id': result['operation_id'],
            'timestamp': result['timestamp'],
            'source_folder': result['source_folder'],
            'dest_folder': result['dest_folder'],
            'total_files': result['moved_count'],
            'total_size': result['total_size'],
            'operations': result['operations'],
            'restored': False
        }
        self.history.append(batch)
        self.save_history()
        
        # رسالة النتيجة
        message = f"تم نقل {result['moved_count']} ملف بنجاح إلى:\n{result['dest_folder']}"
        if result['error_files']:
            message += f"\n\nتعذر نقل {len(result['error_files'])} ملف"
        
        QMessageBox.information(self, "نتيجة العملية", message)
        
        self.play_notification()
        self.log_message(f"اكتمل النقل - {result['moved_count']} ملف", "SUCCESS")

        self.move_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        if hasattr(self, 'trash_btn'):
            self.trash_btn.setEnabled(TRASH_AVAILABLE)
        
        # إعادة البحث
        self.start_search()
    
    def on_move_error(self, error: str):
        """خطأ في النقل"""
        QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء النقل:\n{error}")
        self.log_message(f"خطأ في النقل: {error}", "ERROR")
        
        self.move_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
    
    def show_history_dialog(self):
        """عرض نافذة السجل"""
        if not self.history:
            QMessageBox.information(self, "السجل فارغ", "لا توجد عمليات سابقة")
            return
        
        dialog = HistoryDialog(self.history, self)
        dialog.restore_requested.connect(self.restore_files)
        dialog.exec_()
    
    def restore_files(self, batch: dict):
        """إرجاع الملفات"""
        self.log_message(f"بدء إرجاع الملفات - {batch['total_files']} ملف...")
        
        self.restore_thread = FileRestoreThread(batch)
        self.restore_thread.progress.connect(self.on_search_progress)
        self.restore_thread.finished_restore.connect(self.on_restore_finished)
        self.restore_thread.error.connect(self.on_restore_error)
        self.restore_thread.start()
    
    def on_restore_finished(self, result: dict):
        """انتهاء الإرجاع"""
        # تحديث السجل
        for batch in self.history:
            if batch['operation_id'] == result['operation_id']:
                batch['restored'] = True
                break
        self.save_history()
        
        message = f"تم إرجاع {result['restored_count']} ملف بنجاح"
        if result['error_files']:
            message += f"\n\nتعذر إرجاع {len(result['error_files'])} ملف"
        
        QMessageBox.information(self, "نتيجة الإرجاع", message)
        
        self.play_notification()
        self.log_message(f"اكتمل الإرجاع - {result['restored_count']} ملف", "SUCCESS")
        
        # إعادة البحث إذا كان هناك مجلد محدد
        if self.folder_input.text():
            self.start_search()
    
    def on_restore_error(self, error: str):
        """خطأ في الإرجاع"""
        QMessageBox.critical(self, "خطأ", f"حدث خطأ أثناء الإرجاع:\n{error}")
        self.log_message(f"خطأ في الإرجاع: {error}", "ERROR")
    
    def export_report(self):
        """تصدير التقرير"""
        if not self.similar_groups:
            QMessageBox.warning(self, "تنبيه", "لا توجد نتائج للتصدير")
            return
        
        file_path, file_filter = QFileDialog.getSaveFileName(
            self, "حفظ التقرير",
            f"duplicate_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "Text Files (*.txt);;CSV Files (*.csv)"
        )
        
        if not file_path:
            return
        
        try:
            if file_path.endswith('.csv'):
                self.export_csv(file_path)
            else:
                self.export_txt(file_path)
            
            QMessageBox.information(self, "نجاح", f"تم حفظ التقرير:\n{file_path}")
            self.log_message(f"تم تصدير التقرير: {file_path}", "SUCCESS")
        except Exception as e:
            QMessageBox.critical(self, "خطأ", f"فشل حفظ التقرير:\n{str(e)}")
    
    def export_txt(self, file_path: str):
        """تصدير كـ TXT"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"تقرير الملفات المتقاربة بالحجم\n")
            f.write(f"تاريخ التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"تطوير: {DEVELOPER} | {EMAIL}\n")
            f.write("=" * 80 + "\n\n")
            
            for idx, group in enumerate(self.similar_groups, 1):
                f.write(f"\n{'─' * 60}\n")
                f.write(f"المجموعة {idx} ({len(group)} ملفات)\n")
                f.write(f"{'─' * 60}\n")
                
                for file_info in group:
                    f.write(f"  • {file_info['name']}\n")
                    f.write(f"    الحجم: {self.format_size(file_info['size'])}\n")
                    f.write(f"    المسار: {file_info['path']}\n\n")
    
    def export_csv(self, file_path: str):
        """تصدير كـ CSV"""
        with open(file_path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['المجموعة', 'اسم الملف', 'الحجم (بايت)', 'الحجم', 'الامتداد', 'المسار'])
            
            for idx, group in enumerate(self.similar_groups, 1):
                for file_info in group:
                    writer.writerow([
                        idx,
                        file_info['name'],
                        file_info['size'],
                        self.format_size(file_info['size']),
                        file_info['ext'],
                        file_info['path']
                    ])
    
    def play_notification(self):
        """تشغيل صوت الإشعار"""
        try:
            if SOUND_AVAILABLE:
                # محاولة تشغيل صوت النظام
                QApplication.beep()
        except:
            pass
    
    def clear_log(self):
        """مسح السجل"""
        self.log_text.clear()
    
    def save_log(self):
        """حفظ السجل"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "حفظ السجل",
            f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Text Files (*.txt)"
        )
        
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self.log_text.toPlainText())
            self.log_message(f"تم حفظ السجل: {file_path}", "SUCCESS")
    
    def load_history(self):
        """تحميل سجل العمليات"""
        try:
            history_path = os.path.join(os.path.expanduser("~"), HISTORY_FILE)
            if os.path.exists(history_path):
                with open(history_path, 'r', encoding='utf-8') as f:
                    self.history = json.load(f)
        except Exception as e:
            self.history = []
    
    def save_history(self):
        """حفظ سجل العمليات مع نسخة احتياطية دوّارة."""
        try:
            home = os.path.expanduser("~")
            history_path = os.path.join(home, HISTORY_FILE)

            # نسخة احتياطية للسجل الحالي قبل الكتابة
            if os.path.exists(history_path):
                backup_dir = os.path.join(home, ".history_backup")
                os.makedirs(backup_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = os.path.join(backup_dir, f"history_{ts}.json")
                try:
                    shutil.copy2(history_path, backup_path)
                except (OSError, PermissionError):
                    pass
                # الاحتفاظ بآخر 10 نسخ فقط
                try:
                    backups = sorted(
                        f for f in os.listdir(backup_dir)
                        if f.startswith("history_") and f.endswith(".json")
                    )
                    for old in backups[:-10]:
                        try:
                            os.remove(os.path.join(backup_dir, old))
                        except OSError:
                            pass
                except OSError:
                    pass

            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except (OSError, PermissionError, TypeError) as e:
            self.log_message(f"تعذر حفظ السجل: {e}", "WARNING")
    
    def load_settings(self):
        """تحميل الإعدادات"""
        self.threshold_spin.setValue(
            self.settings.value("threshold", 3.0, type=float)
        )
        self.same_ext_check.setChecked(
            self.settings.value("same_ext", False, type=bool)
        )
        last_folder = self.settings.value("last_folder", "")
        if last_folder and os.path.isdir(last_folder):
            self.folder_input.setText(last_folder)
    
    def save_settings(self):
        """حفظ الإعدادات"""
        self.settings.setValue("threshold", self.threshold_spin.value())
        self.settings.setValue("same_ext", self.same_ext_check.isChecked())
        self.settings.setValue("last_folder", self.folder_input.text())
    
    def closeEvent(self, event):
        """معالجة الإغلاق"""
        # إيقاف الخيوط
        for thread in [self.search_thread, self.move_thread, self.restore_thread]:
            if thread and thread.isRunning():
                thread.stop()
                thread.wait()
        
        # حفظ الإعدادات
        self.save_settings()
        
        event.accept()


# ═══════════════════════════════════════════════════════════════════════════════
# نقطة الدخول
# ═══════════════════════════════════════════════════════════════════════════════

def _load_app_icon() -> QIcon:
    """تحميل أيقونة التطبيق من مجلد assets (ico ثم png عالي الدقة كاحتياطي)."""
    base_dir = Path(__file__).resolve().parent
    candidates = [
        base_dir / "assets" / "icon.ico",
        base_dir / "assets" / "icon.png",
        base_dir / "assets" / "icons" / "icon_256.png",
    ]
    for path in candidates:
        if path.exists():
            return QIcon(str(path))
    return QIcon()


def main():
    """نقطة الدخول الرئيسية"""
    # دعم الشاشات عالية الدقة
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setWindowIcon(_load_app_icon())

    # إعداد الخط
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # إعداد الاتجاه
    app.setLayoutDirection(Qt.RightToLeft)

    # إنشاء النافذة
    window = FileSizeDuplicateFinder()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
