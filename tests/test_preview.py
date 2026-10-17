import io
import json

import pytest
from PySide6.QtCore import Qt
from pypdf import PdfWriter

from repdf.app import MainWindow
from repdf.render_worker import render_document


def make_pdf(path, sizes):
    writer = PdfWriter()
    for width, height in sizes:
        writer.add_blank_page(width=width, height=height)
    writer.write(path)


def wait_for_preview(qtbot, doc):
    qtbot.waitUntil(lambda: doc.ready and doc._render_pending == 0
                   and not doc.render_timer.isActive() and not doc.fit_timer.isActive(), timeout=15000)


@pytest.mark.parametrize("size", [(595, 842), (842, 595)])
def test_fit_page_and_resize_then_manual_zoom(qtbot, tmp_path, size):
    source = tmp_path / "fit.pdf"
    make_pdf(source, [size])
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1000, 800)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    window.fit_action.trigger()
    wait_for_preview(qtbot, doc)
    assert doc.fit_mode
    assert window.fit_action.isChecked()
    card = doc.page_cards[0]
    viewport = doc.scroll_area.viewport()
    assert card.width() <= viewport.width()
    assert card.height() <= viewport.height()
    if size[1] > size[0]:
        assert viewport.height() - card.height() <= 2
    assert abs(card.preview.width() / card.preview.height() - size[0] / size[1]) < .01
    old_zoom = doc.zoom
    window.resize(700, 500)
    qtbot.waitUntil(lambda: doc.zoom < old_zoom)
    wait_for_preview(qtbot, doc)
    assert card.width() <= viewport.width()
    assert card.height() <= viewport.height()
    window._set_manual_zoom(100)
    assert not doc.fit_mode
    assert doc.zoom == 100
    assert not window.fit_action.isChecked()


def test_fit_middle_page_fills_height_without_next_page_peeking(qtbot, tmp_path):
    source = tmp_path / "middle.pdf"
    make_pdf(source, [(595, 842)] * 3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    doc.scroll_area.ensureWidgetVisible(doc.page_cards[1], 0, 0)
    doc.focused_page = 1
    window.fit_action.trigger()
    wait_for_preview(qtbot, doc)
    qtbot.wait(20)
    viewport = doc.scroll_area.viewport()
    card = doc.page_cards[1]
    scroll = doc.scroll_area.verticalScrollBar().value()
    assert doc.fit_page_index == 1
    assert 0 <= viewport.height() - card.height() <= 2
    assert abs(card.y() - scroll) <= 1
    assert doc.page_cards[2].y() - scroll >= viewport.height()


def test_fullscreen_aspect_navigation_escape_and_zoom_preserved(qtbot, tmp_path):
    source = tmp_path / "preview.pdf"
    make_pdf(source, [(595, 842), (842, 595)])
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    doc.page_order = [1, 0]
    doc._reflow_grid()
    doc.focused_page = 1
    window._show_fullscreen_preview()
    viewer = window._fullscreen_preview
    qtbot.waitUntil(lambda: viewer.isFullScreen() and not viewer.image.isNull())
    assert viewer.page_index == 1
    qtbot.waitUntil(lambda: not viewer.timer.isActive() and viewer.render_generation > 0)
    qtbot.waitUntil(lambda: abs(viewer.image.width() - viewer.label.width() * viewer.devicePixelRatioF()) <= 2,
                   timeout=15000)
    pixmap = viewer.label.pixmap()
    displayed = pixmap.size() / pixmap.devicePixelRatio()
    assert displayed.width() <= viewer.width()
    assert displayed.height() <= viewer.height()
    # PDF raster and Qt aspect fitting can each round by one pixel.
    assert min(viewer.width() - displayed.width(),
               viewer.height() - viewer.HEADER_HEIGHT - displayed.height()) <= 2
    qtbot.keyClick(viewer, Qt.Key.Key_Right)
    assert viewer.page_index == 0
    assert viewer.render_generation == -1
    qtbot.keyClick(viewer, Qt.Key.Key_Escape)
    assert window._fullscreen_preview is None
    assert doc.zoom == 100
    assert doc.selected_pages == set()


def test_worker_renders_only_requested_page_and_reports_pdf_size(tmp_path):
    source = tmp_path / "pages.pdf"
    make_pdf(source, [(300, 420), (600, 400)])
    output = io.StringIO()
    render_document(source, 1, tmp_path, 9, output, pages=[1])
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(messages) == 1
    assert messages[0]["page"] == 1
    assert messages[0]["width_points"] == 600
    assert messages[0]["height_points"] == 400
    assert not (tmp_path / "g9-p0.png").exists()


def test_navigation_keys_control_preview_when_slider_has_focus(qtbot, tmp_path):
    source = tmp_path / "keys.pdf"
    make_pdf(source, [(595, 842)] * 3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    window.zoom_slider.setFocus()
    vertical = doc.scroll_area.verticalScrollBar()
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_Down)
    assert vertical.value() > 0
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_Up)
    assert vertical.value() == 0
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageDown)
    assert vertical.value() > 0
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageUp)
    assert vertical.value() == 0
    for key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
        qtbot.keyClick(window.zoom_slider, key)
    assert window.zoom_slider.value() == 100
    assert doc.zoom == 100
    window.fit_action.trigger()
    wait_for_preview(qtbot, doc)
    zoom = doc.zoom
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageDown)
    assert doc.fit_page_index == 1
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_Left)
    assert doc.fit_page_index == 0
    assert doc.zoom == zoom
    assert doc.fit_mode


@pytest.mark.parametrize('fit', [False, True])
def test_home_end_follow_reordered_pages_with_slider_focus(qtbot, tmp_path, fit):
    source = tmp_path / 'home-end.pdf'
    make_pdf(source, [(595, 842)] * 5)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    doc.page_order = [3, 1, 4, 0, 2]
    doc._reflow_grid()
    if fit:
        window.fit_action.trigger()
        wait_for_preview(qtbot, doc)
    zoom = doc.zoom
    window.zoom_slider.setFocus()
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_End)
    if fit:
        wait_for_preview(qtbot, doc)
        qtbot.waitUntil(lambda: not doc._fit_navigation_pending)
        assert doc.fit_page_index == 2
    else:
        vertical = doc.scroll_area.verticalScrollBar()
        assert vertical.value() == min(doc.page_cards[2].y(), vertical.maximum())
    assert doc.preview_page_index() == 2
    assert doc.focused_page == 2
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_Home)
    if fit:
        wait_for_preview(qtbot, doc)
        qtbot.waitUntil(lambda: not doc._fit_navigation_pending)
        assert doc.fit_page_index == 3
        # Repeated/rapid jumps must not leave navigation anchored to an old page.
        qtbot.keyClick(window.zoom_slider, Qt.Key.Key_End)
        qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageUp)
        assert doc.fit_page_index == 0
        qtbot.keyClick(window.zoom_slider, Qt.Key.Key_Home)
        wait_for_preview(qtbot, doc)
        qtbot.waitUntil(lambda: not doc._fit_navigation_pending)
    else:
        assert doc.scroll_area.verticalScrollBar().value() == doc.scroll_area.verticalScrollBar().minimum()
    assert doc.preview_page_index() == 3
    assert doc.focused_page == 3
    assert doc.zoom == zoom


def test_fit_navigation_uses_visible_last_page_and_clamps_boundaries(qtbot, tmp_path):
    source = tmp_path / "boundary.pdf"
    make_pdf(source, [(595, 842)] * 3)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    window.fit_action.trigger()
    wait_for_preview(qtbot, doc)
    assert doc.fit_page_index == 0
    vertical = doc.scroll_area.verticalScrollBar()
    # Scroll to the last page independently of the Fit reference, as with the mouse wheel.
    vertical.setValue(vertical.maximum())
    assert doc.preview_page_index() == 2
    bottom = vertical.value()
    for _ in range(3):
        qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageDown)
        qtbot.wait(10)
        assert doc.fit_page_index == 2
        assert vertical.value() == bottom
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageUp)
    qtbot.wait(20)
    assert doc.fit_page_index == 1
    assert vertical.value() < bottom
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageUp)
    qtbot.wait(20)
    assert doc.fit_page_index == 0
    top = vertical.value()
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageUp)
    assert doc.fit_page_index == 0
    assert vertical.value() == top
    # Rapid navigation must also stop at the last page, without an extra hidden step.
    for _ in range(5):
        qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageDown)
    assert doc.fit_page_index == 2
    qtbot.keyClick(window.zoom_slider, Qt.Key.Key_PageUp)
    assert doc.fit_page_index == 1


@pytest.mark.parametrize("sizes", [[(595, 842), (400, 842)], [(842, 595), (595, 842)]])
def test_preview_centers_pages_with_different_widths(qtbot, tmp_path, sizes):
    source = tmp_path / "center.pdf"
    make_pdf(source, sizes)
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1100, 800)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    qtbot.wait(20)
    viewport = doc.scroll_area.viewport()
    for card in doc.page_cards:
        center = card.mapTo(viewport, card.rect().center())
        assert abs(center.x() - viewport.rect().center().x()) <= 1
    window.fit_action.trigger()
    wait_for_preview(qtbot, doc)
    qtbot.wait(20)
    for card in doc.page_cards:
        center = card.mapTo(viewport, card.rect().center())
        assert abs(center.x() - viewport.rect().center().x()) <= 1


@pytest.mark.parametrize("mode,groups", [
    ("single", [[3], [1], [4], [0], [2]]),
    ("spread", [[3, 1], [4, 0], [2]]),
    ("cover", [[3], [1, 4], [0, 2]]),
])
def test_fullscreen_modes_follow_order_and_sync_selection(qtbot, tmp_path, monkeypatch, mode, groups):
    source = tmp_path / "spread.pdf"
    make_pdf(source, [(595, 842), (842, 595), (595, 842), (595, 842), (400, 700)])
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.load_pdf(source)
    doc = window.current_document()
    wait_for_preview(qtbot, doc)
    doc.page_order = [3, 1, 4, 0, 2]
    doc.page_cards[1].checkbox.click()
    monkeypatch.setattr(doc, "preview_page_index", lambda: 3)
    action = {"single": window.fullscreen_action, "spread": window.spread_action, "cover": window.cover_action}[mode]
    action.trigger()
    viewer = window._fullscreen_preview
    assert viewer.groups == groups
    assert viewer.visible_pages == groups[0]
    assert not viewer.checkboxes[3].isChecked()
    viewer.checkboxes[3].click()
    assert doc.selected_pages == {1, 3}
    assert doc.page_cards[3].checkbox.isChecked()
    qtbot.waitUntil(lambda: viewer.render_generation > 0, timeout=5000)
    qtbot.waitUntil(lambda: all(not image.isNull() for image in viewer.images.values()))
    for index, label in viewer.labels.items():
        assert label.x() >= 0
        assert label.y() >= viewer.HEADER_HEIGHT
        assert label.geometry().right() < viewer.width()
        assert label.geometry().bottom() < viewer.height()
        assert viewer.checkboxes[index].geometry().bottom() < label.y()
    # Navigation works even while the page checkbox has keyboard focus.
    qtbot.keyClick(viewer.checkboxes[3], Qt.Key.Key_End)
    assert viewer.visible_pages == groups[-1]
    last_label = viewer.label
    qtbot.keyClick(viewer, Qt.Key.Key_End)
    assert viewer.label is last_label
    qtbot.keyClick(viewer.checkboxes[groups[-1][0]], Qt.Key.Key_Home)
    assert viewer.visible_pages == groups[0]
    qtbot.keyClick(viewer.checkboxes[3], Qt.Key.Key_PageDown)
    assert viewer.visible_pages == groups[1]
    assert viewer.render_generation == -1
    if 1 in viewer.visible_pages:
        assert viewer.checkboxes[1].isChecked()
        viewer.checkboxes[1].click()
        assert 1 not in doc.selected_pages
        assert not doc.page_cards[1].checkbox.isChecked()
    qtbot.keyClick(viewer, Qt.Key.Key_PageUp)
    assert viewer.visible_pages == groups[0]
    assert viewer.checkboxes[3].isChecked()
    viewer.show_page(2)
    assert viewer.visible_pages == groups[-1]
    qtbot.keyClick(viewer, Qt.Key.Key_Down)
    assert viewer.visible_pages == groups[-1]
    qtbot.keyClick(viewer, Qt.Key.Key_F11 if mode == "cover" else Qt.Key.Key_Escape)
    assert window._fullscreen_preview is None
    assert doc.zoom == 100
    assert window.output_selection()[0].pages == tuple(page for page in doc.page_order if page in doc.selected_pages)

