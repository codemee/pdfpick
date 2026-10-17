import io
import json

import pytest
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent
from PySide6.QtWidgets import QApplication
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from repdf.app import DocumentView, MainWindow
from repdf.preview import FullscreenPreview
from repdf.render_worker import extract_selection_result, serve


def image_pdf(path):
    image = Image.new('RGB', (650, 130), 'white')
    ImageDraw.Draw(image).text((25, 25), 'Region OCR test',
                              font=ImageFont.load_default(size=50), fill='black')
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=400)
    obj = DecodedStreamObject()
    obj.set_data(image.tobytes())
    for key, value in {'/Type': '/XObject', '/Subtype': '/Image', '/ColorSpace': '/DeviceRGB'}.items():
        obj[NameObject(key)] = NameObject(value)
    for key, value in {'/Width': 650, '/Height': 130, '/BitsPerComponent': 8}.items():
        obj[NameObject(key)] = NumberObject(value)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({
        NameObject('/Im0'): writer._add_object(obj)})})
    contents = DecodedStreamObject()
    contents.set_data(b'q 240 0 0 48 30 252 cm /Im0 Do Q')
    page[NameObject('/Contents')] = writer._add_object(contents)
    with path.open('wb') as stream:
        writer.write(stream)


def region_request(path, start, end):
    output = io.StringIO()
    serve(io.StringIO(json.dumps({'type': 'ocr_region', 'source': str(path), 'page': 0,
                                  'start': start, 'end': end, 'generation': 9}) + '\n'), output)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [m['type'] for m in messages] == ['ready', 'text', 'done'], messages
    return messages[1]


def test_region_reads_image_only_pdf_offline(tmp_path, monkeypatch):
    from rapidocr.utils.download_file import DownloadFile
    monkeypatch.setattr(DownloadFile, 'run', lambda *a, **kw: pytest.fail('Unexpected model download'))
    path = tmp_path / 'image.pdf'
    image_pdf(path)
    assert extract_selection_result(path, 0, [.05, .20], [.95, .40], allow_ocr=True)['text'] == ''
    result = region_request(path, [.05, .20], [.95, .40])
    assert result['text'] == 'Region OCR test'
    assert result['ocr_used']
    assert len(result['rects']) == 1
    left, top, right, bottom = result['rects'][0]
    assert .05 <= left < right <= .95 and .20 <= top < bottom <= .40
    reverse = region_request(path, [.95, .40], [.05, .20])
    assert reverse['text'] == result['text']


def test_blank_region_returns_empty_without_copying(tmp_path):
    path = tmp_path / 'image.pdf'
    image_pdf(path)
    result = region_request(path, [0, 0], [1, .1])
    assert result['text'] == '' and result['rects'] == []


def test_region_mode_rectangle_release_copies_and_switches_modes(qtbot, tmp_path, monkeypatch):
    path = tmp_path / 'image.pdf'
    image_pdf(path)
    monkeypatch.setattr(DocumentView, '_queue_all_renders', lambda self: None)
    window = MainWindow()
    qtbot.addWidget(window)
    doc = window._new_document(path)
    doc.loaded(1)
    doc.page_sizes[0] = (300, 400)
    card = doc.page_cards[0]
    image = QImage(300, 400, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    card.set_image(image)
    window._sync_controls()
    window.copy_text_action.trigger()
    window.region_ocr_action.trigger()
    assert not window.copy_text_action.isChecked()
    assert window.region_ocr_action.isChecked()
    assert card.preview.region_mode and card.text_copy_mode
    assert card.preview.cursor().shape() == Qt.CursorShape.CrossCursor
    assert not window.region_ocr_action.icon().isNull()
    QApplication.clipboard().setText('before')
    def mouse(kind, point, buttons):
        QApplication.sendEvent(card.preview, QMouseEvent(kind, point, point, point,
            Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
    mouse(QEvent.Type.MouseButtonPress, QPointF(15, 80), Qt.MouseButton.LeftButton)
    mouse(QEvent.Type.MouseMove, QPointF(285, 160), Qt.MouseButton.LeftButton)
    qtbot.wait(150)
    assert not card.preview._preview_timer.isActive()
    assert not window._text_requests
    assert QApplication.clipboard().text() == 'before'
    assert card.preview._selecting
    mouse(QEvent.Type.MouseButtonRelease, QPointF(285, 160), Qt.MouseButton.NoButton)
    qtbot.waitUntil(lambda: not window._text_requests, timeout=20000)
    assert QApplication.clipboard().text() == 'Region OCR test'
    assert card.preview._highlight_rects
    viewer = FullscreenPreview(window, doc, 0)
    assert viewer.labels[0].region_mode
    viewer.close()
    window.copy_text_action.trigger()
    assert not window.region_ocr_action.isChecked()
    assert not card.preview.region_mode and card.preview.text_mode
    window.copy_text_action.trigger()
    assert not card.preview.text_mode and not card.text_copy_mode
