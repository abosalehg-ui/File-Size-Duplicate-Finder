"""اختبارات دخان للواجهة: بناء النافذة، الثيمان، حالة التحديد، الفلترة.

تُتجاوَز تلقائياً حيث لا تتوفر PyQt5 (بيئة الـ CI مثلاً)، فتبقى اختبارات
المحرك مستقلة عن الواجهة.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt5", reason="الواجهة تحتاج PyQt5")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from finder.gui import icons, theme  # noqa: E402


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setLayoutDirection(Qt.RightToLeft)
    return instance


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    """نافذة معزولة: HOME مؤقت حتى لا تُلمس إعدادات المستخدم ولا سجله."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    from finder.gui.main_window import FileSizeDuplicateFinder

    win = FileSizeDuplicateFinder()
    yield win
    win.close()


def _groups(tmp_path, count=3, per_group=3):
    groups = []
    for gi in range(count):
        payload = bytes([gi]) * (1024 * (gi + 1))
        files = []
        for k in range(per_group):
            path = tmp_path / f"g{gi}_copy{k}.bin"
            path.write_bytes(payload)
            files.append({
                "path": str(path), "name": path.name,
                "size": len(payload), "ext": ".bin",
            })
        groups.append(files)
    return groups


# ── الثيم والأيقونات ─────────────────────────────────────────────────────
@pytest.mark.parametrize("dark", [False, True])
def test_stylesheet_builds_for_both_modes(app, dark):
    qss = theme.stylesheet(dark)
    assert "QPushButton" in qss and "QTreeView" in qss
    # لا تبقى أي علامة تنسيق غير مستبدلة
    assert "{p." not in qss and "{SPACE" not in qss


@pytest.mark.parametrize("dark", [False, True])
def test_every_palette_token_is_a_hex_color(dark):
    palette = theme.palette(dark)
    for field, value in vars(palette).items():
        if field == "dark":
            continue
        assert value.startswith("#") and len(value) in (4, 7), field


def test_icons_render_non_empty(app):
    for name in ("search", "trash", "archive", "layers", "moon", "check"):
        assert not icons.pixmap(name, "#123456", 18).isNull(), name


def test_unknown_icon_is_empty_not_crash(app):
    assert icons.pixmap("no-such-icon", "#123456").isNull()


# ── النافذة ──────────────────────────────────────────────────────────────
def test_window_starts_with_placeholder_and_disabled_actions(window):
    assert window.results_stack.currentWidget() is window.placeholder
    assert not window.move_btn.isEnabled()
    assert not window.trash_btn.isEnabled()
    assert not window.act_export.isEnabled()


def test_theme_toggle_switches_stylesheet_and_icon(window):
    assert not window.dark_mode
    window.set_dark_mode(True)
    assert window.dark_mode
    assert QApplication.instance().styleSheet() == theme.stylesheet(True)
    assert window.act_dark.text() == "الوضع الفاتح"
    window.set_dark_mode(False)
    assert QApplication.instance().styleSheet() == theme.stylesheet(False)


def test_results_populate_tree_and_stats(window, tmp_path):
    groups = _groups(tmp_path)
    window.similar_groups = groups
    window.display_results(groups)
    assert window.results_stack.currentWidget() is window.results_tree
    assert window.results_tree.topLevelItemCount() == 3
    assert window.stat_groups._value.text() == "3"
    assert window.stat_files._value.text() == "9"


def test_select_all_enables_destructive_actions(window, tmp_path):
    groups = _groups(tmp_path)
    window.similar_groups = groups
    window.display_results(groups)
    window.select_all()
    selected, fully = window.get_selected()
    assert sum(len(g) for g in selected) == 9
    assert fully == 3                      # كل المجموعات محددة بالكامل
    assert window.move_btn.isEnabled()
    # تحذير «لن تبقى نسخة» يظهر فور تحديد كل ملفات مجموعة
    assert not window.keep_one_warning.isHidden()
    window.deselect_all()
    assert not window.move_btn.isEnabled()


def test_select_all_in_text_field_selects_text_not_files(window, tmp_path):
    """Ctrl+A داخل حقل نصي يبقى «تحديد النص» — لا يقلب كل الملفات محدَّدة."""
    groups = _groups(tmp_path)
    window.similar_groups = groups
    window.display_results(groups)
    window.show()
    window.filter_input.setFocus()
    if QApplication.focusWidget() is not window.filter_input:
        pytest.skip("البيئة لا تمنح التركيز للحقول")
    window.filter_input.setText("g0_")
    window.select_all()
    assert window.filter_input.selectedText() == "g0_"
    assert window.get_selected() == ([], 0)


def test_smart_select_always_keeps_one_per_group(window, tmp_path):
    groups = _groups(tmp_path)
    window.similar_groups = groups
    window.display_results(groups)
    window.smart_select("newest")
    selected, fully = window.get_selected()
    assert fully == 0                      # لم تُحدَّد مجموعة بالكامل
    assert all(len(g) == 2 for g in selected)


def test_filter_limits_operations_to_visible_rows(window, tmp_path):
    groups = _groups(tmp_path)
    window.similar_groups = groups
    window.display_results(groups)
    window.filter_input.setText("g0_")
    window.select_all()
    selected, _ = window.get_selected()
    # التحديد لا يتجاوز ما يراه المستخدم
    assert len(selected) == 1
    assert all(f["name"].startswith("g0_") for f in selected[0])


def test_filter_with_no_match_shows_placeholder(window, tmp_path):
    groups = _groups(tmp_path)
    window.similar_groups = groups
    window.display_results(groups)
    window.filter_input.setText("لا-يوجد")
    assert window.results_stack.currentWidget() is window.placeholder
    assert window.get_selected() == ([], 0)


def test_size_column_sorts_numerically(window, tmp_path):
    groups = _groups(tmp_path, count=3, per_group=2)
    window.similar_groups = groups
    window.display_results(groups)
    window.results_tree.sortItems(2, Qt.DescendingOrder)
    sizes = [
        window.results_tree.topLevelItem(i).data(2, 0x0101)  # SORT_ROLE
        for i in range(window.results_tree.topLevelItemCount())
    ]
    assert sizes == sorted(sizes, reverse=True)


def test_preview_fills_fields_on_selection(window, tmp_path):
    groups = _groups(tmp_path)
    window.similar_groups = groups
    window.display_results(groups)
    first_file = window.results_tree.topLevelItem(0).child(0)
    window.results_tree.setCurrentItem(first_file)
    assert window.preview_stack.currentIndex() == 1
    assert groups[0][0]["name"] in window.preview_fields["name"]._value.text()


def test_busy_state_turns_primary_button_into_stop(window):
    window._set_busy(True)
    assert window.search_btn.text() == "إيقاف"
    assert window.search_btn.property("variant") == "danger"
    assert not window.progress_bar.isHidden()
    window._set_busy(False)
    assert window.search_btn.text() == "بدء البحث"
    assert window.search_btn.property("variant") == "primary"
