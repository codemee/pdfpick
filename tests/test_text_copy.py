from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from repdf.app import DocumentView, MainWindow
from repdf.preview import FullscreenPreview
from repdf.render_worker import extract_selection, extract_selection_result


def text_pdf(path: Path) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})
    })
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 24 Tf 40 300 Td (Copy this text) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    with path.open('wb') as output:
        writer.write(output)


def test_extract_selection_reads_pdf_text(tmp_path):
    source = tmp_path / 'text.pdf'
    text_pdf(source)
    result = extract_selection_result(source, 0, [0.12, 0.22], [0.78, 0.27])
    assert 'Copy this text' in result['text']
    assert len(result['rects']) >= 12
    assert all(0.1 < box[0] < box[2] < 0.7 for box in result['rects'])


def test_extract_selection_on_rotated_page(tmp_path):
    source = tmp_path / 'text.pdf'
    rotated = tmp_path / 'rotated.pdf'
    text_pdf(source)
    writer = PdfWriter()
    writer.add_page(PdfReader(source).pages[0].rotate(90))
    with rotated.open('wb') as output:
        writer.write(output)
    assert 'Copy this text' in extract_selection(rotated, 0, [0.75, 0.12], [0.75, 0.78])


def test_copy_tool_switches_drag_mode_and_copies_text(qtbot, tmp_path, monkeypatch):
    source = tmp_path / 'text.pdf'
    text_pdf(source)
    monkeypatch.setattr(DocumentView, '_queue_all_renders', lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    doc = window._new_document(source)
    doc.loaded(1)
    card = doc.page_cards[0]
    image = QImage(300, 400, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    card.set_image(image)
    doc.page_sizes[0] = (300, 400)
    window._sync_controls()
    assert not card.preview.text_mode
    assert not window.copy_text_action.icon().isNull()

    window.copy_text_action.trigger()
    assert card.preview.text_mode
    assert card.text_copy_mode
    assert window.toolbar.widgetForAction(window.copy_text_action).isChecked()
    assert 'QToolButton#copyTextTool:checked' in QApplication.instance().styleSheet()
    QApplication.clipboard().setText('before')
    def send_mouse(kind, point, buttons):
        event = QMouseEvent(kind, point, point, point, Qt.MouseButton.LeftButton, buttons,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(card.preview, event)

    send_mouse(QEvent.Type.MouseButtonPress, QPointF(36, 88), Qt.MouseButton.LeftButton)
    send_mouse(QEvent.Type.MouseMove, QPointF(234, 108), Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: bool(card.preview._highlight_rects), timeout=5000)
    assert QApplication.clipboard().text() == 'before'
    send_mouse(QEvent.Type.MouseButtonRelease, QPointF(234, 108), Qt.MouseButton.NoButton)
    generation = window._next_generation
    qtbot.waitUntil(lambda: QApplication.clipboard().text() != 'before', timeout=5000)
    assert 'Copy this text' in QApplication.clipboard().text()
    assert generation not in window._text_requests
    assert card.preview._selection_start is None
    assert len(card.preview._highlight_rects) >= 12
    painted = card.preview.grab().toImage()
    assert painted.pixelColor(45, 90).name() != '#ffffff'
    assert painted.pixelColor(220, 105).name() == '#ffffff'
    viewer = FullscreenPreview(window, doc, 0)
    assert viewer.labels[0].text_mode
    viewer.close()
    window.copy_text_action.trigger()
    assert not card.preview.text_mode
    assert not card.text_copy_mode
    assert not window.toolbar.widgetForAction(window.copy_text_action).isChecked()


def test_image_only_page_does_not_copy(tmp_path):
    source = tmp_path / 'blank.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    with source.open('wb') as output:
        writer.write(output)
    assert extract_selection(source, 0, [0.1, 0.1], [0.8, 0.8]) == ''
