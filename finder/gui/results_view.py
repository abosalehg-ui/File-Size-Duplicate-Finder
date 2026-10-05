"""عرض النتائج: الشجرة، الفلترة، التحديد، ولوحة المعاينة.

مُفصول عن النافذة الرئيسية كـ mixin: يقرأ ويكتب عناصر النافذة نفسها
(`self.results_tree`، `self.preview_fields`، …) لكنه يجمع في مكان واحد كل
ما يخص "ماذا يرى المستخدم من النتائج وماذا حدّد منها". منطق القرار النقي
(الحالة الثلاثية، الاحتفاظ بنسخة) يبقى في `selection.py` المختبَر بلا Qt.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.fileinfo import FileInfo
from ..core.formats import format_bytes
from ..ops.operations import TRASH_AVAILABLE
from . import icons, textfmt, theme
from .selection import (
    STATE_CHECKED, STATE_PARTIAL, group_tristate, partition_keep_one,
)
from .widgets import Card, EmptyState, FieldRow, StatChip, apply_variant

# المجموعات تُفتح تلقائياً فقط إن كان عددها معقولاً
AUTO_EXPAND_GROUP_LIMIT = 100

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg"}

SORT_ROLE = Qt.UserRole + 1


def _file_times(path: str) -> tuple[str | None, str | None]:
    """(تاريخ الإنشاء إن توفر بدقة، تاريخ آخر تعديل).

    st_ctime على غير Windows هو وقت تغيير الـ inode لا الإنشاء،
    لذا لا نعرضه كإنشاء إلا حيث يكون صحيحاً.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None, None
    fmt = "%Y-%m-%d %H:%M"
    modified = datetime.fromtimestamp(st.st_mtime).strftime(fmt)
    created = None
    if sys.platform.startswith("win"):
        created = datetime.fromtimestamp(st.st_ctime).strftime(fmt)
    elif hasattr(st, "st_birthtime"):
        created = datetime.fromtimestamp(st.st_birthtime).strftime(fmt)
    return created, modified


class SortableItem(QTreeWidgetItem):
    """صف يقبل الترتيب بالقيمة الحقيقية لا بالنص.

    بدونه يرتّب Qt عمود الحجم أبجدياً فيأتي «9 KB» بعد «10 MB».
    """

    def __lt__(self, other: QTreeWidgetItem) -> bool:  # type: ignore[override]
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        mine = self.data(column, SORT_ROLE)
        theirs = other.data(column, SORT_ROLE)
        if mine is not None and theirs is not None:
            return mine < theirs
        return self.text(column).lower() < other.text(column).lower()


def iter_visible(tree: QTreeWidget) -> Iterator[tuple[QTreeWidgetItem, list[QTreeWidgetItem]]]:
    """(صف المجموعة، صفوف ملفاتها الظاهرة) لكل مجموعة غير مخفية بالفلتر.

    مصدر واحد لقاعدة "العمليات تنطبق على الظاهر فقط" بدل تكرار نفس الحلقة
    المتداخلة في التحديد والفلترة والتحديد الذكي.
    """
    root = tree.invisibleRootItem()
    for i in range(root.childCount()):
        group = root.child(i)
        if group.isHidden():
            continue
        yield group, [
            group.child(j) for j in range(group.childCount())
            if not group.child(j).isHidden()
        ]


class ResultsViewMixin:
    """الشجرة والفلترة والتحديد والمعاينة — يُخلط مع QMainWindow."""

    def _build_results_card(self) -> QWidget:
        # العنوان ورقائق الإحصاء في صف واحد — يوفّر الطول للشجرة وهي الأهم
        card = Card(compact=True)

        header = QHBoxLayout()
        header.setSpacing(theme.SPACE_SM)
        self.results_title_icon = QLabel()
        self.results_title_icon.setFixedSize(theme.ICON_SM, theme.ICON_SM)
        header.addWidget(self.results_title_icon)
        results_title = QLabel("النتائج")
        results_title.setObjectName("cardTitle")
        header.addWidget(results_title)
        header.addSpacing(theme.SPACE_SM)

        self.stat_groups = StatChip("layers", "مجموعة مكررة")
        self.stat_files = StatChip("copy", "ملف داخل المجموعات")
        self.stat_size = StatChip("hard-drive", "الحجم الكلي")
        self.stat_savings = StatChip("savings", "يمكن تحريره")
        self.stat_chips = [
            self.stat_groups, self.stat_files, self.stat_size, self.stat_savings
        ]
        for chip in self.stat_chips:
            header.addWidget(chip, 1)
        card.body.addLayout(header)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(theme.SPACE_SM)
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText(
            "تصفية بالاسم أو الامتداد — العمليات تنطبق على الظاهر فقط (Ctrl+F)"
        )
        self.filter_input.setAccessibleName("فلترة النتائج")
        self.filter_input.setClearButtonEnabled(True)
        self.filter_input.textChanged.connect(self.apply_results_filter)
        self._filter_icon = QAction(self)
        self.filter_input.addAction(self._filter_icon, QLineEdit.LeadingPosition)
        self._reg_icon(self._filter_icon, "filter", "muted", theme.ICON_SM)
        filter_row.addWidget(self.filter_input, 1)

        self.filter_status = QLabel("")
        self.filter_status.setObjectName("hint")
        filter_row.addWidget(self.filter_status)

        for action in (self.act_expand, self.act_collapse):
            button = QToolButton()
            button.setObjectName("iconOnly")
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            filter_row.addWidget(button)
        card.body.addLayout(filter_row)

        self.results_stack = QStackedWidget()
        # سياسة Ignored رأسياً: الشجرة تتقلّص بحرية إذا ضاق الطول (عند فتح
        # لوحة السجل على نافذة قصيرة مثلاً) بدل أن يتجاوز التخطيط البطاقة
        # فتُرسم أزرار التحديد فوق الصفوف. الحدّ الأدنى يبقي سطراً مرئياً.
        self.results_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.results_stack.setMinimumHeight(40)
        self.results_tree = self._build_tree()
        self.placeholder = EmptyState("search", "", "", "استعراض مجلد")
        self.placeholder.action_clicked.connect(self.browse_folder)
        self._rethemable.append(self.placeholder)
        self.results_stack.addWidget(self.placeholder)
        self.results_stack.addWidget(self.results_tree)
        card.body.addWidget(self.results_stack, 1)

        card.body.addLayout(self._build_select_row())
        return card

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(["", "الملف", "الحجم", "النوع", "المجلد"])
        tree.setAccessibleName("نتائج مجموعات الملفات المتقاربة")
        tree.setAlternatingRowColors(True)
        tree.setUniformRowHeights(True)
        tree.setRootIsDecorated(True)
        tree.setExpandsOnDoubleClick(False)
        tree.setSortingEnabled(True)
        tree.setIndentation(16)
        tree.itemChanged.connect(self.on_item_check_changed)
        tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        tree.itemDoubleClicked.connect(self.open_file_location)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self.show_context_menu)

        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setSortIndicatorShown(True)
        header.setStretchLastSection(False)
        tree.setColumnWidth(0, 46)
        tree.setColumnWidth(4, 230)
        return tree

    def _build_select_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_SM)
        self.select_row_buttons: list[QPushButton] = []
        for action in (
            self.act_select_all, self.act_deselect_all,
            self.act_keep_newest, self.act_keep_oldest,
        ):
            button = QPushButton(action.text().replace("تحديد الكل عدا", "الكل عدا"))
            self._bind(button, action)
            self._reg_icon(button, self._icon_name_of(action), "text", theme.ICON_SM)
            row.addWidget(button)
            self.select_row_buttons.append(button)
        row.addStretch(1)
        export_btn = apply_variant(QPushButton("تصدير التقرير"), "ghost")
        self._bind(export_btn, self.act_export)
        self._reg_icon(export_btn, "download", "muted", theme.ICON_SM)
        row.addWidget(export_btn)
        return row

    def _build_preview_card(self) -> QWidget:
        card = Card("معاينة الملف", "eye")
        self._rethemable.append(card)
        self.preview_stack = QStackedWidget()

        self.preview_empty = EmptyState(
            "eye", "لا ملف محدد", "اختر صفّ ملف من النتائج لعرض تفاصيله هنا."
        )
        self._rethemable.append(self.preview_empty)
        self.preview_stack.addWidget(self.preview_empty)

        # التفاصيل داخل منطقة تمرير، والأزرار مثبّتة أسفلها: إذا قصُر الطول
        # تُمرَّر الحقول بدل أن تتراكب على الأزرار.
        scrolled = QWidget()
        scrolled_layout = QVBoxLayout(scrolled)
        scrolled_layout.setContentsMargins(0, 0, 0, 0)
        scrolled_layout.setSpacing(theme.SPACE_MD)

        thumb_box = QFrame()
        thumb_box.setObjectName("thumbBox")
        thumb_box.setFixedHeight(146)
        thumb_layout = QVBoxLayout(thumb_box)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_thumb = QLabel()
        self.preview_thumb.setAlignment(Qt.AlignCenter)
        thumb_layout.addWidget(self.preview_thumb)
        scrolled_layout.addWidget(thumb_box)

        self.preview_fields = {
            "name": FieldRow("الاسم"),
            "size": FieldRow("الحجم"),
            "ext": FieldRow("النوع"),
            "modified": FieldRow("آخر تعديل"),
            "created": FieldRow("الإنشاء"),
            "dir": FieldRow("المجلد"),
        }
        for field in self.preview_fields.values():
            scrolled_layout.addWidget(field)
        scrolled_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(scrolled)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        scroll.setMinimumHeight(60)

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(theme.SPACE_MD)
        details_layout.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(theme.SPACE_SM)
        open_btn = QPushButton("فتح الموقع")
        open_btn.clicked.connect(self._open_current_location)
        self._reg_icon(open_btn, "external", "text", theme.ICON_SM)
        copy_btn = apply_variant(QPushButton("نسخ المسار"), "ghost")
        copy_btn.clicked.connect(self._copy_current_path)
        self._reg_icon(copy_btn, "copy", "muted", theme.ICON_SM)
        buttons.addWidget(open_btn, 1)
        buttons.addWidget(copy_btn, 1)
        details_layout.addLayout(buttons)

        self.preview_stack.addWidget(details)
        card.body.addWidget(self.preview_stack, 1)
        self.preview_card = card
        return card

    def _display_dir(self, path: str) -> str:
        """مجلد الملف نسبةً إلى جِذر الفحص — أقصر وأسهل مقارنةً."""
        directory = os.path.dirname(path)
        if self._scan_root:
            try:
                relative = os.path.relpath(directory, self._scan_root)
            except ValueError:
                return directory
            return "." if relative == "." else relative
        return directory

    def display_results(self, groups: list[list[FileInfo]]):
        p = theme.palette(self.dark_mode)
        self.results_tree.blockSignals(True)
        self.results_tree.setUpdatesEnabled(False)
        was_sorting = self.results_tree.isSortingEnabled()
        self.results_tree.setSortingEnabled(False)
        try:
            self.results_tree.clear()
            total_files = 0
            total_size = 0
            potential_savings = 0
            expand = len(groups) <= AUTO_EXPAND_GROUP_LIMIT

            for group_idx, group_files in enumerate(groups):
                group_item = SortableItem(self.results_tree)
                group_item.setFlags(group_item.flags() | Qt.ItemIsUserCheckable)
                group_item.setCheckState(0, Qt.Unchecked)
                group_size = sum(f.size for f in group_files)
                by_size = sorted(group_files, key=lambda x: x.size, reverse=True)
                savings = sum(f.size for f in by_size[1:])
                potential_savings += savings

                group_item.setText(
                    1,
                    f"مجموعة {textfmt.num(group_idx + 1)} — "
                    f"{textfmt.count_files(len(group_files))}",
                )
                group_item.setData(1, SORT_ROLE, group_idx)
                group_item.setText(2, textfmt.ltr(format_bytes(group_size)))
                group_item.setData(2, SORT_ROLE, group_size)
                extensions = {f.ext for f in group_files}
                group_item.setText(
                    3,
                    textfmt.ltr(extensions.pop()) or "بدون"
                    if len(extensions) == 1 else "متعدد",
                )
                group_item.setText(
                    4, f"يمكن تحرير {textfmt.ltr(format_bytes(savings))}"
                )
                group_item.setData(4, SORT_ROLE, savings)
                group_item.setToolTip(
                    1,
                    f"{textfmt.count_files(len(group_files))} متطابقة — "
                    f"يمكن تحرير {textfmt.ltr(format_bytes(savings))}",
                )
                group_item.setExpanded(expand)

                for file_info in group_files:
                    file_item = SortableItem(group_item)
                    file_item.setFlags(file_item.flags() | Qt.ItemIsUserCheckable)
                    file_item.setCheckState(0, Qt.Unchecked)
                    # المسارات والأحجام تُعزل اتجاهياً كي لا تُقلبها الواجهة RTL
                    file_item.setText(1, textfmt.ltr(file_info.name))
                    file_item.setData(1, SORT_ROLE, file_info.name.lower())
                    file_item.setText(2, textfmt.ltr(format_bytes(file_info.size)))
                    file_item.setData(2, SORT_ROLE, file_info.size)
                    file_item.setText(3, textfmt.ltr(file_info.ext) or "بدون")
                    directory = self._display_dir(file_info.path)
                    file_item.setText(4, textfmt.ltr(directory))
                    file_item.setData(4, SORT_ROLE, directory.lower())
                    file_item.setData(0, Qt.UserRole, file_info)
                    file_item.setToolTip(1, file_info.path)
                    file_item.setToolTip(4, os.path.dirname(file_info.path))
                    is_image = file_info.ext in IMAGE_EXTS
                    file_item.setIcon(
                        1,
                        icons.icon(
                            "image" if is_image else "file", p.text_muted, theme.ICON_SM
                        ),
                    )
                    total_files += 1
                    total_size += file_info.size

            self.stat_groups.set_value(f"{len(groups)}")
            self.stat_files.set_value(f"{total_files}")
            self.stat_size.set_value(textfmt.ltr(format_bytes(total_size)))
            self.stat_savings.set_value(textfmt.ltr(format_bytes(potential_savings)))
        finally:
            self.results_tree.setSortingEnabled(was_sorting)
            self.results_tree.setUpdatesEnabled(True)
            self.results_tree.blockSignals(False)

        self._style_group_rows()
        if self.filter_input.text():
            self.apply_results_filter(self.filter_input.text())
        else:
            self._show_results_or_placeholder()
        self._update_selection_state()

    def _reset_stats(self):
        for chip in self.stat_chips:
            chip.set_value("—")
        self.filter_status.setText("")

    def _style_group_rows(self):
        """تمييز صفوف المجموعات: خلفية موحّدة + خط عريض + مربّع لون صغير.

        مربّع اللون يفصل المجموعات بصرياً دون تلوين الصف كله، فتبقى الشجرة
        هادئة ويبقى النص مقروءاً في الوضعين.
        """
        if not hasattr(self, "results_tree"):
            return
        p = theme.palette(self.dark_mode)
        accents = theme.group_accents(self.dark_mode)
        row_bg = QColor(p.group_row)
        text_color = QColor(p.text)
        bold = QFont()
        bold.setBold(True)
        root = self.results_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group_item = root.child(i)
            group_item.setIcon(1, QIcon(icons.swatch(accents[i % len(accents)])))
            for col in range(self.results_tree.columnCount()):
                group_item.setBackground(col, row_bg)
                group_item.setForeground(col, text_color)
                group_item.setFont(col, bold)
            group_item.setForeground(4, QColor(p.text_muted))
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                child.setForeground(4, QColor(p.text_muted))
                info = child.data(0, Qt.UserRole)
                is_image = info is not None and info.ext in IMAGE_EXTS
                child.setIcon(
                    1,
                    icons.icon(
                        "image" if is_image else "file", p.text_muted, theme.ICON_SM
                    ),
                )

    def _show_placeholder(self, kind: str):
        content = {
            "initial": (
                "search", "لم يبدأ البحث بعد",
                "اختر مجلداً ثم اضغط «بدء البحث» — أو اسحب المجلد إلى النافذة مباشرة.",
            ),
            "searching": (
                "clock", "جاري الفحص…",
                "يمكنك الإيقاف في أي لحظة، والنتائج ستظهر هنا عند الانتهاء.",
            ),
            "empty": (
                "shield", "لا توجد ملفات مكررة",
                "لم تُطابِق أي ملفات المعايير الحالية. جرّب تفعيل «المجلدات الفرعية» "
                "أو رفع حد التقارب أو تبديل وضع الكشف.",
            ),
            "filtered": (
                "filter", "لا نتائج للفلتر",
                "لا مجموعة تطابق نص التصفية الحالي. امسح الفلتر لعرض كل النتائج.",
            ),
        }[kind]
        self.placeholder.set_content(*content)
        self.placeholder.retheme(self.dark_mode)
        if self.placeholder.button is not None:
            self.placeholder.button.setVisible(kind == "initial")
        self.results_stack.setCurrentWidget(self.placeholder)

    def _show_results_or_placeholder(self):
        if not self.similar_groups:
            self._show_placeholder("empty" if self._scan_root else "initial")
            return
        root = self.results_tree.invisibleRootItem()
        visible = any(
            not root.child(i).isHidden() for i in range(root.childCount())
        )
        if visible:
            self.results_stack.setCurrentWidget(self.results_tree)
        else:
            self._show_placeholder("filtered")

    def expand_all_groups(self):
        self.results_tree.expandAll()

    def collapse_all_groups(self):
        self.results_tree.collapseAll()

    def _focus_filter(self):
        self.filter_input.setFocus()
        self.filter_input.selectAll()

    def apply_results_filter(self, text: str):
        text = (text or "").strip().lower()
        root = self.results_tree.invisibleRootItem()
        total = root.childCount()
        shown = 0
        for i in range(total):
            group_item = root.child(i)
            any_visible = False
            for j in range(group_item.childCount()):
                child = group_item.child(j)
                if not text:
                    child.setHidden(False)
                    any_visible = True
                else:
                    match = (text in child.text(1).lower()
                             or text in child.text(3).lower())
                    child.setHidden(not match)
                    any_visible = any_visible or match
            group_item.setHidden(bool(text) and not any_visible)
            shown += int(not group_item.isHidden())
        self.filter_status.setText(
            f"{textfmt.num(shown)} من {textfmt.num(total)} مجموعة"
            if text and total else ""
        )
        self._show_results_or_placeholder()
        self._update_selection_state()

    def on_item_check_changed(self, item: QTreeWidgetItem, column: int):
        """مزامنة حالة المجموعة/الملفات. تحديد مجموعة يشمل ملفاتها
        الظاهرة فقط — الصفوف المخفية بالفلتر لا تُمس أبداً."""
        if column != 0 or self._updating_checks:
            return
        self._updating_checks = True
        try:
            if item.parent() is None:
                group = item
                state = item.checkState(0)
                if state != Qt.PartiallyChecked:
                    for j in range(item.childCount()):
                        child = item.child(j)
                        if not child.isHidden():
                            child.setCheckState(0, state)
            else:
                group = item.parent()
                self._sync_group_state(group)
        finally:
            self._updating_checks = False
        # نقرة واحدة تغيّر مجموعة واحدة: يُعاد حساب ملخصها فقط لا الشجرة كلها
        self._schedule_group_update(group)

    def _sync_group_state(self, group_item: QTreeWidgetItem):
        visible = checked = 0
        for j in range(group_item.childCount()):
            child = group_item.child(j)
            if child.isHidden():
                continue
            visible += 1
            if child.checkState(0) == Qt.Checked:
                checked += 1
        # قرار الحالة الثلاثية في وحدة نقية مُختبَرة (selection.group_tristate)
        state = group_tristate(visible, checked)
        qt_state = {
            STATE_CHECKED: Qt.Checked,
            STATE_PARTIAL: Qt.PartiallyChecked,
        }.get(state, Qt.Unchecked)
        group_item.setCheckState(0, qt_state)

    def _set_all_checks(self, state):
        self._updating_checks = True
        self.results_tree.setUpdatesEnabled(False)
        try:
            for group, visible in iter_visible(self.results_tree):
                for child in visible:
                    child.setCheckState(0, state)
                self._sync_group_state(group)
        finally:
            self.results_tree.setUpdatesEnabled(True)
            self._updating_checks = False
        self._update_selection_state()

    def select_all(self):
        # Ctrl+A داخل حقل نصي يجب أن يظل «تحديد النص» لا «تحديد كل الملفات»
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit):
            focused.selectAll()
            return
        self._set_all_checks(Qt.Checked)

    def deselect_all(self):
        self._set_all_checks(Qt.Unchecked)

    def smart_select(self, keep: str = "newest"):
        """تحديد كل ملفات كل مجموعة ظاهرة ما عدا واحد يُحتفظ به
        (الأحدث أو الأقدم تعديلاً) — فتبقى نسخة دائماً."""
        self._updating_checks = True
        self.results_tree.setUpdatesEnabled(False)
        try:
            for group, visible in iter_visible(self.results_tree):
                # القرار في وحدة نقية مُختبَرة: أي الملفات تُحدَّد وأيّها يبقى.
                # FileInfo يُقارن بالهوية، فيُحتفظ بعنصر واحد بعينه حتى لو
                # تساوت سجلات الملفات قيمةً.
                infos = [(c, c.data(0, Qt.UserRole)) for c in visible]
                to_select, _kept = partition_keep_one(
                    [info for _c, info in infos if info is not None], keep=keep
                )
                select_ids = {id(info) for info in to_select}
                for child, info in infos:
                    child.setCheckState(
                        0, Qt.Checked if id(info) in select_ids else Qt.Unchecked
                    )
                self._sync_group_state(group)
        finally:
            self.results_tree.setUpdatesEnabled(True)
            self._updating_checks = False
        label = "الأحدث" if keep == "newest" else "الأقدم"
        self._update_selection_state()
        self.log_message(f"تحديد ذكي: كل الملفات عدا {label} في كل مجموعة")
        self.status_bar.showMessage(f"تم تحديد كل الملفات عدا {label} في كل مجموعة", 5000)

    @staticmethod
    def _group_selection(
        group: QTreeWidgetItem, visible: list[QTreeWidgetItem]
    ) -> tuple[list[FileInfo], bool]:
        """(ملفات المجموعة المحددة الظاهرة، هل حُدِّد كل ملفاتها)."""
        files = []
        for child in visible:
            if child.checkState(0) == Qt.Checked:
                info = child.data(0, Qt.UserRole)
                if info is not None:
                    files.append(info)
        return files, bool(files) and len(files) == group.childCount()

    def get_selected(self) -> tuple[list[list[FileInfo]], int]:
        """(المجموعات المحددة، عدد المجموعات المحدد كل ملفاتها).

        تُحتسب فقط العناصر الظاهرة (غير المخفية بالفلتر) — ما لا يراه
        المستخدم لا يدخل في أي عملية. تُقرأ من الشجرة مباشرة لا من الملخص
        المخزّن، لأن نتيجتها تُمرَّر لعمليات نقل وحذف.
        """
        selected_groups: list[list[FileInfo]] = []
        fully_selected = 0
        for group, visible in iter_visible(self.results_tree):
            files, fully = self._group_selection(group, visible)
            if files:
                selected_groups.append(files)
                fully_selected += int(fully)
        return selected_groups, fully_selected

    # ── ملخص التحديد ─────────────────────────────────────────────────────
    def _init_selection_tracking(self):
        """ملخص تحديد لكل مجموعة يُحدَّث تدريجياً.

        كان كل نقر على صندوق يعيد المرور على الشجرة كلها؛ مع آلاف المجموعات
        يصبح التأخير ملحوظاً. الآن تُعاد حسبة المجموعة التي تغيّرت فقط، وتُدمج
        النقرات المتتالية في تحديث واحد عبر مؤقت بزمن صفر.
        """
        # id(صف المجموعة) → (ملفاتها المحددة، محددة بالكامل؟)
        self._selection_by_group: dict[int, tuple[list[FileInfo], bool]] = {}
        self._dirty_groups: dict[int, QTreeWidgetItem] = {}
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(0)
        self._selection_timer.timeout.connect(self._flush_group_updates)

    def _schedule_group_update(self, group: QTreeWidgetItem):
        self._dirty_groups[id(group)] = group
        self._selection_timer.start()

    def _flush_group_updates(self):
        for key, group in self._dirty_groups.items():
            if group.isHidden():
                self._selection_by_group.pop(key, None)
                continue
            visible = [
                group.child(j) for j in range(group.childCount())
                if not group.child(j).isHidden()
            ]
            files, fully = self._group_selection(group, visible)
            if files:
                self._selection_by_group[key] = (files, fully)
            else:
                self._selection_by_group.pop(key, None)
        self._dirty_groups.clear()
        self._refresh_selection_summary()

    def _update_selection_state(self):
        """إعادة بناء ملخص التحديد كاملاً ثم تحديث شريط الإجراءات.

        تُستدعى بعد التغييرات الشاملة (عرض نتائج، فلترة، تحديد الكل، انشغال)؛
        نقرات الصناديق المفردة تمر بالمسار التدريجي `_schedule_group_update`.
        """
        self._selection_timer.stop()
        self._dirty_groups.clear()
        self._selection_by_group = {}
        for group, visible in iter_visible(self.results_tree):
            files, fully = self._group_selection(group, visible)
            if files:
                self._selection_by_group[id(group)] = (files, fully)
        self._refresh_selection_summary()

    def _refresh_selection_summary(self):
        """تحديث شريط الإجراءات ليصف التحديد الحالي بدقة.

        الأزرار المدمّرة تبقى معطّلة حتى يوجد تحديد فعلي — أفضل من السماح
        بالضغط ثم إظهار «الرجاء التحديد».
        """
        summaries = self._selection_by_group.values()
        count = sum(len(files) for files, _fully in summaries)
        size = sum(f.size for files, _fully in summaries for f in files)
        groups = len(self._selection_by_group)
        fully = sum(1 for _files, is_full in summaries if is_full)

        if count:
            self.selection_summary.setText(
                f"محدد: {textfmt.count_files(count)} في "
                f"{textfmt.count_groups(groups)} · "
                f"{textfmt.ltr(format_bytes(size))}"
            )
        else:
            self.selection_summary.setText("لم تحدد أي ملف بعد")

        p = theme.palette(self.dark_mode)
        self.selection_icon.setPixmap(
            icons.pixmap(
                "check-square" if count else "square",
                p.primary if count else p.text_muted,
                theme.ICON_MD,
            )
        )
        if fully:
            self.keep_one_warning.setText(
                f"⚠ كل ملفات {fully} مجموعة محددة — لن تبقى نسخة"
            )
            self.keep_one_warning.setStyleSheet(f"color: {p.danger};")
            self.keep_one_warning.setVisible(True)
        else:
            self.keep_one_warning.setVisible(False)

        enabled = bool(count) and not self._busy
        self.move_btn.setEnabled(enabled)
        self.trash_btn.setEnabled(enabled and TRASH_AVAILABLE)
        self.act_move.setEnabled(enabled)
        self.act_trash.setEnabled(enabled and TRASH_AVAILABLE)
        has_results = bool(self.similar_groups)
        for action in (
            self.act_select_all, self.act_deselect_all,
            self.act_keep_newest, self.act_keep_oldest,
            self.act_export, self.act_expand, self.act_collapse,
            self.act_focus_filter,
        ):
            action.setEnabled(has_results and not self._busy)
        self.filter_input.setEnabled(has_results and not self._busy)

    def on_tree_selection_changed(self):
        items = self.results_tree.selectedItems()
        info = items[0].data(0, Qt.UserRole) if items else None
        if not info:
            self._clear_preview()
            return
        self._current_preview = info
        created, modified = _file_times(info.path)
        fields = self.preview_fields
        fields["name"].set_value(textfmt.ltr(info.name), info.path)
        fields["size"].set_value(textfmt.ltr(format_bytes(info.size)))
        fields["ext"].set_value(textfmt.ltr(info.ext) or "بدون امتداد")
        fields["modified"].set_value(textfmt.ltr(modified or "") or "—")
        fields["created"].set_value(textfmt.ltr(created or "") or "—")
        fields["created"].setVisible(bool(created))
        directory = os.path.dirname(info.path)
        fields["dir"].set_value(
            textfmt.ltr(self._display_dir(info.path)), directory
        )
        self.preview_stack.setCurrentIndex(1)
        self._refresh_preview_visuals()

    def _clear_preview(self):
        self._current_preview = None
        if hasattr(self, "preview_stack"):
            self.preview_stack.setCurrentIndex(0)

    def _refresh_preview_visuals(self):
        if not hasattr(self, "preview_thumb"):
            return
        info = self._current_preview
        if not info:
            return
        p = theme.palette(self.dark_mode)
        path, ext = info.path, info.ext
        if ext in IMAGE_EXTS and os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                self.preview_thumb.setPixmap(
                    pix.scaled(200, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        self.preview_thumb.setPixmap(icons.pixmap("file", p.border_strong, 46))

    def _open_current_location(self):
        if self._current_preview:
            self._open_folder_of(self._current_preview.path)

    def _copy_current_path(self):
        if not self._current_preview:
            return
        QApplication.clipboard().setText(self._current_preview.path)
        self.status_bar.showMessage("تم نسخ مسار الملف", 3000)

    def _open_folder_of(self, path: str):
        folder = os.path.dirname(path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        self.log_message(f"فتح المجلد: {folder}")

    def open_file_location(self, item: QTreeWidgetItem, column: int):
        info = item.data(0, Qt.UserRole)
        if info:
            self._open_folder_of(info.path)
        else:
            item.setExpanded(not item.isExpanded())

    def show_context_menu(self, position):
        item = self.results_tree.itemAt(position)
        if item is None:
            return
        p = theme.palette(self.dark_mode)
        menu = QMenu(self)
        info = item.data(0, Qt.UserRole)
        if info:
            open_action = menu.addAction(
                icons.icon("external", p.text, theme.ICON_SM), "فتح موقع الملف"
            )
            open_action.triggered.connect(lambda: self._open_folder_of(info.path))
            copy_action = menu.addAction(
                icons.icon("copy", p.text, theme.ICON_SM), "نسخ المسار"
            )
            copy_action.triggered.connect(
                lambda: QApplication.clipboard().setText(info.path)
            )
            menu.addSeparator()
            checked = item.checkState(0) == Qt.Checked
            toggle = menu.addAction(
                icons.icon("square" if checked else "check-square", p.text, theme.ICON_SM),
                "إلغاء تحديد هذا الملف" if checked else "تحديد هذا الملف",
            )
            toggle.triggered.connect(
                lambda: item.setCheckState(0, Qt.Unchecked if checked else Qt.Checked)
            )
        else:
            group_checked = item.checkState(0) == Qt.Checked
            toggle = menu.addAction(
                icons.icon(
                    "square" if group_checked else "check-square", p.text, theme.ICON_SM
                ),
                "إلغاء تحديد المجموعة" if group_checked else "تحديد المجموعة كلها",
            )
            toggle.triggered.connect(
                lambda: item.setCheckState(
                    0, Qt.Unchecked if group_checked else Qt.Checked
                )
            )
            expand = menu.addAction(
                icons.icon(
                    "collapse" if item.isExpanded() else "expand", p.text, theme.ICON_SM
                ),
                "طيّ المجموعة" if item.isExpanded() else "توسيع المجموعة",
            )
            expand.triggered.connect(lambda: item.setExpanded(not item.isExpanded()))
        menu.exec_(self.results_tree.viewport().mapToGlobal(position))

    def _remove_paths_from_results(self, removed: set[str]):
        """إزالة الملفات المنقولة/المحذوفة من النتائج دون إعادة بحث كامل.
        المجموعات التي بقي فيها ملف واحد لم تعد مجموعات تكرار فتُحذف."""
        new_groups = []
        for group in self.similar_groups:
            remaining = [f for f in group if f.path not in removed]
            if len(remaining) > 1:
                new_groups.append(remaining)
        self.similar_groups = new_groups
        self._clear_preview()
        self.display_results(new_groups)
