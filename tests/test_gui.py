from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pypdf import PdfReader, PdfWriter

from pdfpick.app import MainWindow, load_app_icon


def test_drag_preview_animates_and_cancel_restores_order(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_queue_all_renders", lambda: None)
    window.zoom_slider.setValue(25)
    window._pdf_loaded(0, Path("sample.pdf"), 4)
    window.show()
    qtbot.wait(50)
    host = window.grid_host
    original = [card.pos() for card in window.page_cards]
    source = window.page_cards[3]
    host.begin_drag(source)
    target = host._slots[0]
    host.preview_at(QPoint(target.left() + 2, target.center().y()))
    assert host._insertion == 0
    assert window.page_order == [0, 1, 2, 3]
    assert not source.isVisible()
    qtbot.waitUntil(lambda: window.page_cards[0].pos() == original[1])
    # Hit testing still uses the original position after its card has moved.
    host.preview_at(QPoint(target.left() + 2, target.center().y()))
    assert host._insertion == 0
    host.finish_drag()
    qtbot.waitUntil(lambda: [card.pos() for card in window.page_cards] == original)
    assert source.isVisible()
    assert window.page_order == [0, 1, 2, 3]


def test_drag_insertion_commits_preview_order_across_rows(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_queue_all_renders", lambda: None)
    window.zoom_slider.setValue(25)
    window._pdf_loaded(0, Path("sample.pdf"), 8)
    window.show()
    qtbot.wait(50)
    host = window.grid_host
    host.begin_drag(window.page_cards[0])
    target = host._slots[-1]
    host.preview_at(QPoint(target.right(), target.center().y()))
    assert host._insertion == 7
    window._insert_page(0, host._insertion)
    host.finish_drag()
    assert window.page_order == [1, 2, 3, 4, 5, 6, 7, 0]
    assert [window.grid.itemAt(i).widget().page_index for i in range(8)] == window.page_order
    host.begin_drag(window.page_cards[0])
    target = host._slots[1]
    host.preview_at(QPoint(target.left(), target.center().y()))
    window._insert_page(0, host._insertion)
    host.finish_drag()
    assert window.page_order == [1, 0, 2, 3, 4, 5, 6, 7]


def test_drag_thumbnail_contains_preview_and_is_bounded(qtbot) -> None:
    from pdfpick.widgets import PageCard

    card = PageCard(0, 600)
    qtbot.addWidget(card)
    image = QImage(600, 800, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    card.set_image(image)
    card.show()
    thumbnail = card.drag_pixmap()
    assert not thumbnail.isNull()
    assert thumbnail.width() <= 180
    assert thumbnail.height() <= 240
    assert thumbnail.toImage().pixelColor(thumbnail.width() // 2, thumbnail.height() // 2).red() == 255


def test_initial_controls(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.zoom_slider.minimum() == 25
    assert window.zoom_slider.maximum() == 200
    assert window.zoom_slider.value() == 100
    assert not window.export_action.isEnabled()
    assert not window.split_action.isEnabled()
    assert not window.odd_checkbox.isEnabled()
    assert not load_app_icon().isNull()


def test_toolbar_shortcuts_and_zoom_limits(qtbot, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(MainWindow, "choose_pdf", lambda self: calls.append("open"))
    monkeypatch.setattr(MainWindow, "choose_output", lambda self: calls.append("export"))
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.activateWindow()
    qtbot.wait(50)
    for action in (window.open_action, window.export_action):
        assert action in window.toolbar.actions()
        assert not action.icon().isNull()
    assert window.zoom_reset_action.icon().isNull()
    assert window.zoom_in_action not in window.toolbar.actions()
    assert window.zoom_out_action not in window.toolbar.actions()
    display_width = window.zoom_display.width()
    qtbot.keyClick(window, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert calls == ["open"]
    window.export_action.setEnabled(True)
    qtbot.keyClick(window, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert calls == ["open", "export"]
    qtbot.keyClick(window, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    assert window.zoom_slider.value() == 125
    qtbot.keyClick(window, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    assert window.zoom_slider.value() == 100
    window.zoom_slider.setValue(200)
    assert not window.zoom_in_action.isEnabled()
    qtbot.keyClick(window, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert window.zoom_slider.value() == 100
    assert window.zoom_in_action.isEnabled()
    window.zoom_slider.setValue(25)
    assert not window.zoom_out_action.isEnabled()
    assert window.zoom_reset_action.text() == "25%"
    assert window.zoom_display.width() == display_width


def test_failed_load_resets_title_and_open_action(qtbot, monkeypatch, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: None)
    window._update_window_title(tmp_path / "bad.pdf")
    window.open_action.setEnabled(False)
    window._pdf_load_failed(window.session_id, "無法讀取")
    assert "bad.pdf" not in window.windowTitle()
    assert window.open_action.isEnabled()


def test_page_selection_updates_bulk_states(qtbot, monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    writer = PdfWriter()
    for _ in range(4):
        writer.add_blank_page(width=300, height=420)
    with source.open("wb") as stream:
        writer.write(stream)

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_queue_all_renders", lambda: None)
    window.session_id = 1
    window._pdf_loaded(1, source, 4)

    window.page_cards[0].checkbox.click()
    assert window.selected_pages == {0}
    assert window.odd_checkbox.checkState() == Qt.CheckState.PartiallyChecked
    assert window.export_action.isEnabled()
    assert window.split_action.isEnabled()

    window.odd_checkbox.click()
    assert {0, 2} <= window.selected_pages
    assert window.odd_checkbox.checkState() == Qt.CheckState.Checked


def test_zoom_is_debounced(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(window, "_queue_all_renders", lambda: calls.append(True))
    window.source_path = Path("sample.pdf")
    window.page_count = 1
    window._create_page_cards()

    window.zoom_slider.setValue(120)
    window.zoom_slider.setValue(140)
    qtbot.wait(300)
    assert calls == [True]
    assert window.zoom_reset_action.text() == "140%"


def test_pdf_loads_and_renders_page_previews(qtbot, tmp_path: Path) -> None:
    source = tmp_path / "preview.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=420)
    writer.add_blank_page(width=420, height=300)
    with source.open("wb") as stream:
        writer.write(stream)

    window = MainWindow()
    qtbot.addWidget(window)
    window.load_pdf(source)

    qtbot.waitUntil(lambda: len(window.page_cards) == 2, timeout=5_000)
    qtbot.waitUntil(
        lambda: all(not card.preview.pixmap().isNull() for card in window.page_cards),
        timeout=10_000,
    )
    assert str(source.resolve()) in window.windowTitle()
    assert window.page_cards[0].preview.pixmap().width() == 400


def test_reorder_keeps_original_parity_and_export_order(qtbot, monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "reordered.pdf"
    writer = PdfWriter()
    for width in (200, 300, 400, 500):
        writer.add_blank_page(width=width, height=width + 100)
    with source.open("wb") as stream:
        writer.write(stream)

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_queue_all_renders", lambda: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    window.session_id = 1
    window._pdf_loaded(1, source, 4)

    window._move_page(0, 2)
    window._move_page(3, 1)
    assert window.page_order == [3, 1, 2, 0]
    assert [window.grid.itemAt(index).widget().page_index for index in range(4)] == window.page_order

    window.odd_checkbox.click()
    assert window.selected_pages == {0, 2}
    assert window.page_cards[0].checkbox.isChecked()
    assert window.page_cards[2].checkbox.isChecked()
    assert window.odd_checkbox.checkState() == Qt.CheckState.Checked

    window._start_export(output)
    qtbot.waitUntil(lambda: not window._export_running, timeout=5_000)
    reader = PdfReader(output)
    assert [int(page.mediabox.width) for page in reader.pages] == [400, 200]


def test_split_uses_display_order_and_save_dialog(qtbot, monkeypatch, tmp_path) -> None:
    source = tmp_path / "source.pdf"
    writer = PdfWriter()
    for width in (200, 300, 400):
        writer.add_blank_page(width=width, height=500)
    with source.open("wb") as stream:
        writer.write(stream)
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "_queue_all_renders", lambda: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(tmp_path / "single.pdf"), ""))
    window._pdf_loaded(0, source, 3)
    window._move_page(2, 0)
    window.odd_checkbox.click()
    window.choose_split_output()
    assert not window.split_action.isEnabled()
    assert not window.export_action.isEnabled()
    qtbot.waitUntil(lambda: not window._export_running, timeout=5_000)
    assert window.split_action.isEnabled()
    assert not (tmp_path / "single.pdf").exists()
    assert [int(PdfReader(tmp_path / f"single_{i:02d}.pdf").pages[0].mediabox.width)
            for i in (1, 2)] == [400, 200]
    existing = tmp_path / "single_01.pdf"
    before = existing.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
    window.choose_split_output()
    assert not window._export_running
    assert existing.read_bytes() == before
