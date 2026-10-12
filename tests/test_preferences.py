from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QSettings, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from repdf.app import DocumentView, MainWindow
from repdf import __version__
from repdf.core import export_documents
from repdf.preferences import migrate_preferences, system_language
from repdf.strings import localize_text


def test_language_cycle_retranslates_existing_pages_without_changing_state(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    doc = window._new_document(tmp_path / "單數頁.pdf")
    doc.loaded(3)
    doc.page_cards[2].checkbox.click()
    doc._move_page(2, 0)
    window.zoom_slider.setValue(75)
    assert window.language_controller.mode == "system"
    window.language_action.trigger()
    assert window.language_controller.mode == "zh"
    window.language_action.trigger()
    assert window.language_controller.mode == "en"
    assert window.odd_checkbox.text() == "Odd pages"
    assert window.open_action.text() == "Open PDF"
    assert "Zoom in" in window.zoom_reset_action.toolTip()
    assert doc.page_cards[0].checkbox.text() == "Page 1"
    assert doc.page_cards[0].drag_handle.text() == "☰ Reorder"
    assert "Include this file" in doc.include_checkbox.toolTip()
    assert doc.page_order == [2, 0, 1] and doc.selected_pages == {2} and doc.zoom == 75
    assert window.tabs.tabText(0) == "單數頁"
    assert window.windowTitle() == f"RePDF {__version__}"
    assert window.tabs.tabToolTip(0) == str(doc.source_path)
    with pytest.raises(ValueError, match="Select at least one page"):
        export_documents([], tmp_path / "out.pdf")
    window.language_action.trigger()
    assert window.language_controller.mode == "system"
    assert window.windowTitle() == f"RePDF {__version__}"
    assert window.odd_checkbox.text() == "單數頁"
    assert doc.page_cards[0].checkbox.text() == "第 1 頁"


def test_theme_cycle_respects_manual_override_and_system_changes(qtbot, monkeypatch):
    scheme = [Qt.ColorScheme.Dark]
    hints = SimpleNamespace(colorScheme=lambda: scheme[0])
    monkeypatch.setattr("repdf.theme.QGuiApplication.styleHints", lambda: hints)
    window = MainWindow()
    qtbot.addWidget(window)
    theme = window._theme_controller
    color = lambda: QApplication.palette().color(QPalette.ColorRole.Window).name()
    assert theme.mode == "system" and color() == "#202124"
    window.theme_action.trigger()
    assert theme.mode == "light" and color() == "#f5f6f8"
    theme.apply()
    assert color() == "#f5f6f8"
    window.theme_action.trigger()
    assert theme.mode == "dark" and color() == "#202124"
    scheme[0] = Qt.ColorScheme.Light
    theme.apply()
    assert color() == "#202124"
    window.theme_action.trigger()
    assert theme.mode == "system" and color() == "#f5f6f8"
    scheme[0] = Qt.ColorScheme.Dark
    theme.apply()
    assert color() == "#202124"
    assert window.language_controller.mode == "system"


def test_preferences_are_restored_on_next_window(qtbot):
    first = MainWindow()
    qtbot.addWidget(first)
    first.language_action.trigger()
    first.language_action.trigger()
    first.theme_action.trigger()
    first.theme_action.trigger()
    first.close()
    second = MainWindow()
    qtbot.addWidget(second)
    assert second.language_controller.mode == "en"
    assert second._theme_controller.mode == "dark"
    assert second.odd_checkbox.text() == "Odd pages"


def test_locale_change_only_affects_system_mode(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr("repdf.preferences.system_language", lambda: "en")
    QApplication.sendEvent(window, QEvent(QEvent.Type.LocaleChange))
    assert window.odd_checkbox.text() == "Odd pages"
    window.language_controller.set_mode("zh")
    QApplication.sendEvent(window, QEvent(QEvent.Type.LocaleChange))
    assert window.odd_checkbox.text() == "單數頁"


@pytest.mark.parametrize("locale,expected", [("zh_TW", "zh"), ("zh_CN", "zh"), ("en_US", "en"), ("fr_FR", "en")])
def test_system_locale_resolution(monkeypatch, locale, expected):
    original_locale = QLocale(locale)
    monkeypatch.setattr("repdf.preferences.QLocale", SimpleNamespace(system=lambda: original_locale, Language=QLocale.Language))
    assert system_language() == expected


def test_dialog_translations_and_unknown_text_fallback(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    translate = lambda text: QCoreApplication.translate("QFileDialog", text)
    assert translate("File &name:") == "檔案名稱(&N)："
    assert translate("An unknown message") == "An unknown message"
    window.language_controller.set_mode("en")
    assert translate("File &name:") == "File &name:"
    assert translate("&Yes") == "&Yes"
    assert localize_text("已載入 2 頁；已選取 1 頁") == "Loaded 2 pages; 1 selected"
    window.language_controller.set_mode("zh")
    assert localize_text("Loaded 2 pages; 1 selected") == "已載入 2 頁；已選取 1 頁"


def test_system_language_uses_display_language_before_region(monkeypatch):
    locale = SimpleNamespace(uiLanguages=lambda: ["en-US"], language=lambda: QLocale.Language.Chinese)
    monkeypatch.setattr("repdf.preferences.QLocale", SimpleNamespace(system=lambda: locale, Language=QLocale.Language))
    assert system_language() == "en"


def test_rename_migrates_preferences_without_overwriting_current_choices(tmp_path):
    old = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    new = QSettings(str(tmp_path / "new.ini"), QSettings.Format.IniFormat)
    old.setValue("ui/language", "en")
    old.setValue("ui/theme", "dark")
    new.setValue("ui/theme", "light")
    migrate_preferences(new, old)
    assert new.value("ui/language") == "en"
    assert new.value("ui/theme") == "light"
    assert old.value("ui/theme") == "dark"
