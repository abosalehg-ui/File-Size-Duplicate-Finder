<div align="center">

<img src="assets/icons/icon_256.png" alt="App Icon" width="160" height="160">

# 🔍 أداة لعزل الملفات المتقاربة بالحجم
## File Size Duplicate Finder

<img src="https://img.shields.io/badge/Python-3.7+-blue.svg" alt="Python">
<img src="https://img.shields.io/badge/PyQt5-5.15+-green.svg" alt="PyQt5">
<img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg" alt="Platform">
<img src="https://img.shields.io/badge/Version-3.0-orange.svg" alt="Version">
<img src="https://img.shields.io/badge/License-All%20Rights%20Reserved-red.svg" alt="License">

**أداة متقدمة للبحث عن الملفات المكررة وعزلها — كشف بالحجم أو بالـ Hash، بحث متداخل، واجهة بـ Drag & Drop ووضع داكن**

[العربية](#العربية) | [English](#english)

</div>

---

# العربية

## 📖 نظرة عامة

**أداة عزل الملفات المتقاربة بالحجم** هي تطبيق سطح مكتب احترافي مبني بـ PyQt5 يساعدك على:

- 🔎 اكتشاف الملفات المكررة المحتملة بثلاثة أوضاع (حجم / Partial hash / SHA-256 كامل)
- 🌳 مسح الأشجار العميقة من المجلدات الفرعية بسرعة عالية
- 🗑️ نقل الملفات إلى سلة المحذوفات أو إلى مجلد منظّم — مع معاينة قبل التنفيذ
- 🔄 استرداد أي عملية حتى بعد إغلاق التطبيق

## 📸 لقطات الشاشة

<div align="center">

| الواجهة الرئيسية | نتائج البحث |
|:---:|:---:|
| ![الشاشة الرئيسية](screenshots/screenshot1.png) | ![النتائج](screenshots/screenshot2.png) |

</div>

## ✨ المميزات الكاملة

### 🔍 محرّك البحث (الإصدار 3.0)
| الميزة | الوصف |
|--------|-------|
| **3 أوضاع كشف** | حجم متقارب (سريع) • Partial hash (متوازن، يقرأ 128KB) • SHA-256 كامل (دقيق 100%) |
| **بحث متداخل** | مسح المجلدات الفرعية مع تجاهل تلقائي لـ `.git` و `node_modules` و `venv` ... |
| **خوارزمية O(n log n)** | نافذة منزلقة (sliding window) — قابلة للتعامل مع 10K+ ملف بكفاءة |
| **Hash Cache** | تخزين مؤقت لقيم الـ hash يتجاهل تلقائياً عند تعديل الملف |
| **فلترة بالامتداد** | البحث في ملفات بنفس الامتداد فقط |
| **حد تقارب قابل للتعديل** | بالميجابايت (0 = تطابق دقيق، الافتراضي 3MB) |

### 🛡️ ميزات الأمان
| الميزة | الوصف |
|--------|-------|
| **🆕 معاينة العملية (Dry-run)** | جدول تفصيلي قبل النقل/الحذف — تأكيد إجباري |
| **🆕 سلة المحذوفات** | إرسال الملفات إلى سلة محذوفات النظام (قابلة للاسترداد) |
| **🆕 نسخ احتياطية دوّارة** | يحفظ آخر 10 نسخ من السجل تلقائياً في `~/.history_backup/` |
| **🆕 تنبيه للعمليات الكبيرة** | يحذّر عند تجاوز 100 ملف أو 1GB |
| **استرداد العمليات** | إرجاع الملفات إلى مواقعها الأصلية حتى بعد إغلاق التطبيق |
| **معالجة تصادم الأسماء** | إعادة تسمية تلقائية عند وجود ملف بنفس الاسم في الوجهة |

### 🎨 الواجهة (UX)
| الميزة | الوصف |
|--------|-------|
| **🆕 السحب والإفلات** | اسحب أي مجلد على نافذة التطبيق لتعيينه كمسار البحث |
| **🆕 الوضع الداكن** | تبديل بنقرة من شريط العنوان — يُحفظ بين الجلسات |
| **🆕 شريط فلتر مباشر** | اكتب لتصفية النتائج فورياً (اسم/امتداد) |
| **🆕 معاينة الصور** | thumbnail مصغّر بجانب التفاصيل النصية |
| **تلوين المجموعات** | 15 لون مميز لتمييز المجموعات بصرياً |
| **القائمة السياقية** | نقر يمين لفتح موقع الملف أو تحديده |
| **شاشات عالية الدقة** | High-DPI scaling تلقائي |
| **ثنائية اللغة** | عربي (RTL) مع نصوص إنجليزية في README |

### 📤 التصدير والتقارير
| الميزة | الوصف |
|--------|-------|
| **تصدير TXT** | تقرير نصي منسّق |
| **تصدير CSV** | متوافق مع Excel/LibreOffice (UTF-8 BOM للعربية) |
| **🆕 تصدير JSON** | عبر CLI — منظّم وقابل للاستهلاك من سكربتات |
| **سجل العمليات** | تبويب منفصل بألوان للأخطاء والتحذيرات |

### 💻 واجهة سطر الأوامر (CLI) — جديد!
استخدم محرّك البحث من سكربتات أو مهام مجدولة دون فتح الواجهة:

```bash
# بحث أساسي
python file_finder_cli.py --scan /path/to/folder --threshold 3

# بحث متداخل بـ SHA-256 وتصدير CSV
python file_finder_cli.py --scan /data --recursive --mode full --output report.csv

# تصدير JSON بصيغة منظّمة
python file_finder_cli.py --scan /data --recursive --mode partial \
    --output result.json --quiet
```

| المعامل | الوصف |
|---------|-------|
| `--scan PATH` | (مطلوب) مسار المجلد |
| `--threshold MB` | حد التقارب بالميجابايت (افتراضي 0) |
| `--recursive` | بحث متداخل |
| `--same-ext` | نفس الامتداد فقط |
| `--mode size\|partial\|full` | وضع الكشف |
| `--output FILE` | الصيغة من الامتداد: `.csv` / `.json` / `.txt` |
| `--quiet` / `--verbose` | تحكم في الإخراج |

## 💻 متطلبات التشغيل

- Python 3.7+
- PyQt5 5.15+
- send2trash (اختياري لسلة المحذوفات)

## 🚀 التثبيت والتشغيل

```bash
# 1. استنساخ المشروع
git clone https://github.com/abosalehg-ui/File-Size-Duplicate-Finder.git
cd File-Size-Duplicate-Finder

# 2. تثبيت المتطلبات
pip install -r requirements.txt

# 3. تشغيل التطبيق
python file_size_duplicate_finder.py

# أو استخدم CLI
python file_finder_cli.py --scan /path --recursive
```

### بناء تنفيذي مستقل (PyInstaller)

```bash
pip install pyinstaller
pyinstaller build.spec --clean
# الناتج: dist/FileSizeDuplicateFinder(.exe)
```

## 📖 طريقة الاستخدام

### البحث عن الملفات
1. اضغط **"استعراض"** أو **اسحب مجلداً** على النافذة
2. اضبط **حد التقارب** بالميجابايت
3. اختر **وضع الكشف** من القائمة المنسدلة:
   - `حجم متقارب`: مقارنة الأحجام فقط (الأسرع)
   - `Partial hash`: نفس الحجم + بصمة بداية/نهاية (متوازن)
   - `تكرار حقيقي SHA-256`: تطابق المحتوى الكامل (الأدق)
4. فعّل **"المجلدات الفرعية"** للبحث المتداخل (اختياري)
5. اضغط **"🔍 بدء البحث"**

### عزل أو حذف الملفات
1. حدّد الملفات بالنقر على ☐
2. اختر إحدى العمليتين:
   - **📦 عزل المحدد**: نقل إلى `duplicates_sorted/folder_N`
   - **🗑️ سلة المحذوفات**: إرسال إلى سلة النظام (قابلة للاسترداد)
3. **راجع نافذة المعاينة** التي تعرض كل ملف سيتأثر
4. اضغط **"✅ تأكيد"** أو **"❌ إلغاء"**

### استرداد الملفات
- اضغط **"🔄 إرجاع الملفات"** → اختر العملية → **"إرجاع"**
- نسخ احتياطية للسجل تُحفظ في `~/.history_backup/` (آخر 10)

## 📁 هيكل المشروع

```
File-Size-Duplicate-Finder/
├── file_size_duplicate_finder.py    # التطبيق الرئيسي (GUI)
├── file_finder_cli.py               # واجهة سطر الأوامر
├── build.spec                       # PyInstaller config
├── requirements.txt                 # تبعيات التشغيل
├── requirements-dev.txt             # تبعيات التطوير
├── README.md
├── assets/
│   ├── icon.svg                     # المصدر vector
│   ├── icon.ico / icon.png          # أيقونات للتطبيق
│   └── icons/                       # أحجام متعددة (16 → 1024)
└── screenshots/
```

## 📄 ملفات البيانات

- `~/file_finder_history.json` — سجل عمليات النقل (مع نسخ احتياطية في `~/.history_backup/`)
- `~/.file_finder_hash_cache.json` — تخزين مؤقت لقيم الـ hash
- `QSettings` — الإعدادات (آخر مجلد، الحد، الوضع الداكن، إلخ)

## 🛣️ خارطة الطريق

تم تنفيذه ✅:
- المرحلة 3: كشف التكرار الحقيقي بالـ Hashing (Partial + Full)
- المرحلة 4: البحث المتداخل + خوارزمية O(n log n)
- المرحلة 5: ميزات الأمان (Dry-run, send2trash, backups)
- المرحلة 6: تحسينات الواجهة (Drag-drop, Dark mode, فلتر, معاينة صور)
- المرحلة 7: واجهة سطر الأوامر (CLI)
- المرحلة 8: PyInstaller spec للتوزيع

قيد التخطيط:
- المرحلة 1: إعادة هيكلة الكود إلى حزمة Python (refactor)
- المرحلة 2: نظام ترجمة كامل (i18n) مع تبديل اللغة من القائمة
- إحصائيات مرئية (رسوم بيانية لتوزيع الأحجام)
- مقارنة بين مجلدين
- استرداد متعدد (Batch undo)
- GitHub Actions CI لبناء الـ executables تلقائياً

---

# English

## 📖 Overview

**File Size Duplicate Finder** (v3.0) is a professional PyQt5 desktop app for finding and isolating duplicate files. Features three detection modes (size / partial hash / full SHA-256), recursive scanning, drag-and-drop, dark mode, recycle-bin integration, and a standalone CLI.

## ✨ Key Features

### Search Engine
- 🔍 **Three detection modes**: size threshold • partial hash (head+tail MD5) • full SHA-256
- 🌳 **Recursive scanning** with auto-exclusion of `.git`, `node_modules`, etc.
- ⚡ **O(n log n) sliding-window** grouping algorithm
- 💾 **Hash cache** invalidates automatically on file mtime/size change

### Safety
- 👁️ **Dry-run preview** dialog before every move/delete
- 🗑️ **Recycle bin** integration via `send2trash` (recoverable deletions)
- 💾 **Rolling history backups** (last 10) in `~/.history_backup/`
- ⚠️ **Large-operation warnings** (>100 files or >1GB)
- 🔄 **Operation restore** — even after closing the app

### UX
- 🎨 **Dark mode** with persisted preference
- 📥 **Drag & drop** folder onto window
- 🔎 **Live filter bar** for instant result filtering
- 🖼️ **Image thumbnails** in preview panel
- 🌈 **Color-coded groups** (15 distinct colors)
- 📺 **High-DPI** scaling

### Reports & CLI
- 📤 Export to **TXT / CSV / JSON**
- 💻 **Standalone CLI** (no PyQt5 needed):
  ```bash
  python file_finder_cli.py --scan /data --recursive --mode full --output report.csv
  ```

## 💻 Requirements

- Python 3.7+
- PyQt5 5.15+
- send2trash (optional)

## 🚀 Installation

```bash
git clone https://github.com/abosalehg-ui/File-Size-Duplicate-Finder.git
cd File-Size-Duplicate-Finder
pip install -r requirements.txt
python file_size_duplicate_finder.py
```

## 📖 Usage

1. Click **Browse** or **drag a folder** onto the window
2. Adjust **size threshold** (MB)
3. Choose **detection mode** (size / partial / full)
4. Enable **Subdirectories** if needed
5. Click **🔍 Start Search**
6. Select files → **📦 Isolate** or **🗑️ Trash**
7. Review preview dialog → **✅ Confirm**

---

<div align="center">

## 👨‍💻 المطور | Developer

**عبدالكريم العبود | Abdulkarim Alaboud**

📧 [abo.saleh.g@gmail.com](mailto:abo.saleh.g@gmail.com)

---

## 📜 حقوق الملكية | Copyright

© 2025 **File Size Duplicate Finder** - All Rights Reserved

تم التطوير بـ ❤️ باستخدام Python و PyQt5

</div>
