from pathlib import Path
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pypdf import PdfReader, PdfWriter

from repdf.app import DocumentView, MainWindow, load_app_icon
from repdf import __version__


def ready_document(window, path, count, *, zoom=100):
    doc = window._new_document(path)
    doc.zoom = zoom
    doc.loaded(count)
    window.zoom_slider.blockSignals(True)
    window.zoom_slider.setValue(zoom)
    window.zoom_slider.blockSignals(False)
    window._sync_controls()
    return doc


def test_drag_preview_animates_and_cancel_restores_order(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window.zoom_slider.setValue(25)
    doc = ready_document(window, Path("sample.pdf"), 4, zoom=25)
    window.show()
    qtbot.wait(50)
    host = doc.grid_host
    original = [card.pos() for card in doc.page_cards]
    source = doc.page_cards[3]
    host.begin_drag(source)
    target = host._slots[0]
    host.preview_at(QPoint(target.left() + 2, target.center().y()))
    assert host._insertion == 0
    assert doc.page_order == [0, 1, 2, 3]
    assert not source.isVisible()
    qtbot.waitUntil(lambda: doc.page_cards[0].pos() == original[1])
    # Hit testing still uses the original position after its card has moved.
    host.preview_at(QPoint(target.left() + 2, target.center().y()))
    assert host._insertion == 0
    host.finish_drag()
    qtbot.waitUntil(lambda: [card.pos() for card in doc.page_cards] == original)
    assert source.isVisible()
    assert doc.page_order == [0, 1, 2, 3]


def test_drag_insertion_commits_preview_order_across_rows(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window.zoom_slider.setValue(25)
    doc = ready_document(window, Path("sample.pdf"), 8, zoom=25)
    window.show()
    qtbot.wait(50)
    host = doc.grid_host
    host.begin_drag(doc.page_cards[0])
    target = host._slots[-1]
    host.preview_at(QPoint(target.right(), target.center().y()))
    assert host._insertion == 7
    doc._insert_page(0, host._insertion)
    host.finish_drag()
    assert doc.page_order == [1, 2, 3, 4, 5, 6, 7, 0]
    assert [doc.grid.itemAt(i).widget().page_index for i in range(8)] == doc.page_order
    host.begin_drag(doc.page_cards[0])
    target = host._slots[1]
    host.preview_at(QPoint(target.left(), target.center().y()))
    doc._insert_page(0, host._insertion)
    host.finish_drag()
    assert doc.page_order == [1, 0, 2, 3, 4, 5, 6, 7]


def test_drag_thumbnail_contains_preview_and_is_bounded(qtbot) -> None:
    from repdf.widgets import PageCard

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


def test_platform_close_shortcut_closes_only_current_tab(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    first = ready_document(window, tmp_path / "first.pdf", 1)
    second = ready_document(window, tmp_path / "second.pdf", 1)
    third = ready_document(window, tmp_path / "third.pdf", 1)
    first.page_cards[0].checkbox.click()
    window.tabs.setCurrentWidget(second)
    window.activateWindow()
    qtbot.wait(50)
    assert window.close_tab_action.shortcuts() == QKeySequence.keyBindings(QKeySequence.StandardKey.Close)
    assert "W" in second.close_button.toolTip()
    window._set_export_running(True)
    assert not window.close_tab_action.isEnabled()
    window._set_export_running(False)
    modifier = Qt.KeyboardModifier.MetaModifier if sys.platform == "darwin" else Qt.KeyboardModifier.ControlModifier
    qtbot.keyClick(window, Qt.Key.Key_W, modifier)
    assert window.ordered_documents() == [first, third]
    assert first.selected_pages == {0}
    assert window.current_document() is third
    if QKeySequence("Ctrl+F4") in window.close_tab_action.shortcuts():
        qtbot.keyClick(window, Qt.Key.Key_F4, Qt.KeyboardModifier.ControlModifier)
    else:
        window.close_tab_action.trigger()
    assert window.ordered_documents() == [first]
    window.close_tab_action.trigger()
    assert window.tabs.count() == 0
    assert not window.close_tab_action.isEnabled()
    assert window.isVisible()


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
    doc = window._new_document(tmp_path / "bad.pdf")
    window._pdf_load_failed(doc.document_id, "無法讀取")
    assert "bad.pdf" not in window.windowTitle()
    assert window.open_action.isEnabled()
    assert window.tabs.count() == 0


def test_page_selection_updates_bulk_states(qtbot, monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    writer = PdfWriter()
    for _ in range(4):
        writer.add_blank_page(width=300, height=420)
    with source.open("wb") as stream:
        writer.write(stream)

    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    doc = ready_document(window, source, 4)

    doc.page_cards[0].checkbox.click()
    assert doc.selected_pages == {0}
    assert window.odd_checkbox.checkState() == Qt.CheckState.PartiallyChecked
    assert window.export_action.isEnabled()
    assert window.split_action.isEnabled()

    window.odd_checkbox.click()
    assert {0, 2} <= doc.selected_pages
    assert window.odd_checkbox.checkState() == Qt.CheckState.Checked


def test_zoom_is_debounced(qtbot, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: calls.append(self.document_id))
    window = MainWindow()
    qtbot.addWidget(window)
    doc = ready_document(window, Path("sample.pdf"), 1)
    window.zoom_slider.setValue(120)
    window.zoom_slider.setValue(140)
    qtbot.wait(300)
    assert calls == [doc.document_id]
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
    doc = window.current_document()

    qtbot.waitUntil(lambda: len(doc.page_cards) == 2, timeout=5_000)
    qtbot.waitUntil(
        lambda: all(not card.preview.pixmap().isNull() for card in doc.page_cards),
        timeout=10_000,
    )
    assert window.windowTitle() == f"RePDF {__version__}"
    assert window.tabs.tabToolTip(0) == str(source.resolve())
    assert doc.page_cards[0].preview.pixmap().width() == 400


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
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    doc = ready_document(window, source, 4)

    doc._move_page(0, 2)
    doc._move_page(3, 1)
    assert doc.page_order == [3, 1, 2, 0]
    assert [doc.grid.itemAt(index).widget().page_index for index in range(4)] == doc.page_order

    window.odd_checkbox.click()
    assert doc.selected_pages == {0, 2}
    assert doc.page_cards[0].checkbox.isChecked()
    assert doc.page_cards[2].checkbox.isChecked()
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
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(tmp_path / "single.pdf"), ""))
    doc = ready_document(window, source, 3)
    doc._move_page(2, 0)
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


def test_tabs_keep_independent_state_and_output_scope(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    a = ready_document(window, tmp_path / "a.pdf", 4, zoom=25)
    a.page_cards[0].checkbox.click()
    a._move_page(3, 0)
    b = ready_document(window, tmp_path / "b.pdf", 4, zoom=150)
    window.odd_checkbox.click()
    assert a.selected_pages == {0}
    assert b.selected_pages == {0, 2}
    assert window.tabs.tabText(0) == "a"
    assert window.tabs.tabText(1) == "b"
    assert window.windowTitle() == f"RePDF {__version__}"
    assert window.tabs.tabToolTip(1) == str(b.source_path)
    assert not a.include_checkbox.isChecked()
    assert not b.include_checkbox.isChecked()
    assert [item.source for item in window.output_selection()] == [b.source_path]
    a.include_checkbox.setChecked(True)
    assert window.current_document() is b
    assert [item.source for item in window.output_selection()] == [a.source_path]
    b.include_checkbox.setChecked(True)
    window.tabs.tabBar().moveTab(1, 0)
    assert [item.source for item in window.output_selection()] == [b.source_path, a.source_path]
    assert window.output_selection()[0].pages == (0, 2)
    window.tabs.setCurrentWidget(a)
    assert window.zoom_slider.value() == 25
    assert a.page_order == [3, 0, 1, 2]
    assert window.odd_checkbox.checkState() == Qt.CheckState.PartiallyChecked
    window.tabs.setCurrentWidget(b)
    assert window.zoom_slider.value() == 150
    assert window.odd_checkbox.checkState() == Qt.CheckState.Checked


def test_checked_empty_tab_does_not_fall_back(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    a = ready_document(window, tmp_path / "a.pdf", 2)
    b = ready_document(window, tmp_path / "b.pdf", 2)
    b.page_cards[0].checkbox.click()
    a.include_checkbox.setChecked(True)
    assert window.output_selection() == []
    assert not window.export_action.isEnabled()
    a.include_checkbox.setChecked(False)
    assert window.export_action.isEnabled()


def test_duplicate_path_and_same_name_in_other_directory(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    a = ready_document(window, tmp_path / "one" / "report.pdf", 2)
    b = ready_document(window, tmp_path / "two" / "report.pdf", 3)
    window.load_pdf(a.source_path)
    assert window.tabs.count() == 2
    assert window.current_document() is a
    assert window.tabs.tabText(0) == window.tabs.tabText(1) == "report"
    assert window.tabs.tabToolTip(0) != window.tabs.tabToolTip(1)
    window.close_tab(window.tabs.indexOf(b))
    window.close_tab(window.tabs.indexOf(a))
    assert window.tabs.count() == 0
    assert not window.export_action.isEnabled()
    assert str(a.source_path) not in window.windowTitle()


def test_scroll_position_is_kept_per_document(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    a = ready_document(window, tmp_path / "a.pdf", 4)
    b = ready_document(window, tmp_path / "b.pdf", 4)
    window.show()
    window.tabs.setCurrentWidget(a)
    qtbot.wait(50)
    a.scroll_area.verticalScrollBar().setValue(120)
    window.tabs.setCurrentWidget(b)
    qtbot.wait(50)
    b.scroll_area.verticalScrollBar().setValue(230)
    window.tabs.setCurrentWidget(a)
    qtbot.wait(50)
    assert a.scroll_area.verticalScrollBar().value() == 120
    assert b.scroll_area.verticalScrollBar().value() == 230


def test_load_batch_preserves_order_and_successes(qtbot, monkeypatch, tmp_path) -> None:
    from PySide6.QtCore import QMimeData, QUrl

    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: errors.append(text))
    a, bad, b = [tmp_path / name for name in ("a.pdf", "bad.pdf", "b.pdf")]
    for path in (a, b):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        with path.open("wb") as stream:
            writer.write(stream)
    bad.write_text("invalid")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *_args: ([str(a), str(bad), str(b)], ""))
    window = MainWindow()
    qtbot.addWidget(window)
    window.choose_pdf()
    qtbot.waitUntil(lambda: not window._load_batches, timeout=5_000)
    assert [doc.source_path for doc in window.ordered_documents()] == [a, b]
    assert window.current_document().source_path == b
    assert len(errors) == 1 and "bad.pdf" in errors[0]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(a)), QUrl.fromLocalFile(str(b))])

    class Event:
        def mimeData(self):
            return mime

        def acceptProposedAction(self):
            pass

    assert window._dropped_pdfs(Event()) == [a, b]
    window.dropEvent(Event())
    assert window.tabs.count() == 2


def test_previews_route_to_origin_and_closed_results_are_cleaned(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    a = ready_document(window, tmp_path / "a.pdf", 1)
    b = ready_document(window, tmp_path / "b.pdf", 1)
    image = QImage(20, 30, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.red)
    a.render_generation = 100
    window._render_documents[100] = a.document_id
    path = Path(window.preview_temp.name) / "g100-p0.png"
    image.save(str(path))
    window._handle_render_message({"type": "page", "generation": 100, "page": 0, "path": str(path)})
    assert a.page_cards[0].preview.pixmap().width() == 20
    assert b.page_cards[0].preview.pixmap().isNull()
    assert not path.exists()
    window.close_tab(window.tabs.indexOf(a))
    image.save(str(path))
    window._handle_render_message({"type": "page", "generation": 100, "page": 0, "path": str(path)})
    assert not path.exists()
    assert b.page_cards[0].preview.pixmap().isNull()


def test_multi_export_follows_tab_order_and_allows_view_switch(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(DocumentView, "_queue_all_renders", lambda self: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
    window = MainWindow()
    qtbot.addWidget(window)
    docs = []
    for name, widths in (("a", (200, 300)), ("b", (400, 500))):
        path = tmp_path / f"{name}.pdf"
        writer = PdfWriter()
        for width in widths:
            writer.add_blank_page(width=width, height=600)
        with path.open("wb") as stream:
            writer.write(stream)
        doc = ready_document(window, path, 2)
        doc.page_cards[0].checkbox.click()
        doc.page_cards[1].checkbox.click()
        doc.include_checkbox.setChecked(True)
        docs.append(doc)
    docs[1]._move_page(1, 0)
    window.tabs.tabBar().moveTab(1, 0)
    output = tmp_path / "merged.pdf"
    window._start_export(output)
    assert not docs[0].include_checkbox.isEnabled()
    assert not docs[1].page_cards[0].checkbox.isEnabled()
    assert not window.tabs.isMovable()
    window.close_tab(0)
    assert window.tabs.count() == 2
    window.tabs.setCurrentWidget(docs[0])
    qtbot.waitUntil(lambda: not window._export_running, timeout=5_000)
    assert [int(page.mediabox.width) for page in PdfReader(output).pages] == [500, 400, 200, 300]
    assert window.tabs.isMovable()
    window._start_export(tmp_path / "single.pdf", split=True)
    window.tabs.setCurrentWidget(docs[1])
    qtbot.waitUntil(lambda: not window._export_running, timeout=5_000)
    assert [int(PdfReader(tmp_path / f"single_{i:02d}.pdf").pages[0].mediabox.width)
            for i in range(1, 5)] == [500, 400, 200, 300]


def test_close_loading_document_ignores_delayed_result(qtbot, tmp_path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    doc = window._new_document(tmp_path / "a.pdf")
    window.close_tab(0)
    window._pdf_loaded(doc.document_id, doc.source_path, 2)
    assert window.tabs.count() == 0
    assert not window.documents


def test_real_multi_file_previews_survive_rapid_switch_and_zoom(qtbot, tmp_path) -> None:
    paths = []
    for name, width in (("a", 180), ("b", 300)):
        path = tmp_path / f"{name}.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=width, height=400)
        with path.open("wb") as stream:
            writer.write(stream)
        paths.append(path)
    window = MainWindow()
    qtbot.addWidget(window)
    window.load_pdfs(paths)
    qtbot.waitUntil(lambda: all(doc.ready for doc in window.documents.values()), timeout=5_000)
    a, b = window.ordered_documents()
    window.tabs.setCurrentWidget(a)
    window.zoom_slider.setValue(200)
    window.zoom_slider.setValue(50)
    window.tabs.setCurrentWidget(b)
    qtbot.waitUntil(lambda: a.page_cards[0].preview.pixmap().width() == 120
                   and b.page_cards[0].preview.pixmap().width() == 400, timeout=10_000)
    assert a.zoom == 50 and b.zoom == 100
    assert a.render_generation != b.render_generation
