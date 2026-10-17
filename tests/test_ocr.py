import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMarginsF, QPointF, QSizeF
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from repdf import render_worker
from repdf.app import DocumentView, MainWindow
from repdf.ocr import OcrError, _clean_line, _line_regions, suspicious_text
from test_text_copy import text_pdf

pytestmark = pytest.mark.usefixtures('qapp')


def damaged_pdf(path, *, lines=('Copy this text',), point_size=24):
    # Use a real embedded font: PDFium can repair simple Helvetica mappings itself.
    family = 'Arial'
    for location in ('C:/Windows/Fonts/arial.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
                     '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(location).is_file():
            font_id = QFontDatabase.addApplicationFont(location)
            if font_id >= 0:
                family = QFontDatabase.applicationFontFamilies(font_id)[0]
                break
    else:
        pytest.skip('A system font is needed to generate the damaged-mapping fixture')
    pdf = QPdfWriter(str(path))
    pdf.setResolution(72)
    pdf.setPageSize(QPageSize(QSizeF(300, 400), QPageSize.Unit.Point))
    pdf.setPageMargins(QMarginsF(0, 0, 0, 0))
    painter = QPainter(pdf)
    painter.setFont(QFont(family, point_size))
    for row, line in enumerate(lines):
        painter.drawText(QPointF(40, 100 + row * point_size * 1.5), line)
    painter.end()
    del pdf
    writer = PdfWriter(clone_from=path)
    for ref in writer.pages[0]['/Resources']['/Font'].values():
        font = ref.get_object()
        original = font['/ToUnicode'].get_data()
        assert b'<0043>' in original
        cmap = DecodedStreamObject()
        cmap.set_data(original.replace(b'<0043>', b'<FFFD>'))
        font[NameObject('/ToUnicode')] = writer._add_object(cmap)
    with path.open('wb') as output:
        writer.write(output)


@pytest.mark.parametrize('text', ['normal 中文', '若 ﬁ', '\ue000', 'line\r\n\tend', '𠮷'])
def test_valid_text_does_not_trigger_ocr(text):
    assert not suspicious_text(text)


@pytest.mark.parametrize('text', ['�作細節', 'text\x00', 'bad\ud800', 'bad\x01', '\uffff', '\ufdd0'])
def test_explicit_corruption_triggers_ocr(text):
    assert suspicious_text(text)


def test_cjk_cleanup_keeps_english_word_boundaries():
    assert _clean_line('把 現在 的 文件 README file') == '把現在的文件 README file'


def test_line_regions_keep_dashes_and_underscores_with_text():
    # A list marker comes first; an underscore sits below the letters without
    # overlapping them. Both must stay in their text line, not become OCR rows.
    rects = [[.08, .20999, .09, .21], [.1, .205, .12, .207], [.13, .2, .2, .21],
             [.20, .211, .21, .212], [.21, .2, .3, .21],
             [.1, .235, .12, .237], [.13, .23, .3, .24]]
    assert _line_regions(rects) == [[.08, .2, .3, .212], [.1, .23, .3, .24]]


def test_ocr_runs_only_for_damaged_final_selection(tmp_path, monkeypatch):
    source = tmp_path / 'text.pdf'
    text_pdf(source)
    calls = []
    monkeypatch.setattr(render_worker, 'recognize_selection',
                        lambda page, rects: calls.append(rects) or 'Copy this text')
    args = (source, 0, [.12, .22], [.78, .27])
    assert render_worker.extract_selection_result(*args, allow_ocr=True)['text'] == 'Copy this text'
    assert not calls
    damaged_pdf(source)
    preview = render_worker.extract_selection_result(*args)
    assert suspicious_text(preview['text'])
    assert not calls  # Highlight updates must not run OCR.
    progress = []
    result = render_worker.extract_selection_result(*args, allow_ocr=True,
                                                   on_ocr=lambda: progress.append(True))
    assert result['text'] == 'Copy this text'
    assert result['ocr_used']
    assert calls == [preview['rects']]
    assert result['rects'] == preview['rects']
    assert progress == [True]


def test_ocr_failure_preserves_original_and_reports_reason(tmp_path, monkeypatch):
    source = tmp_path / 'damaged.pdf'
    damaged_pdf(source)
    def unavailable(*args):
        raise OcrError('Missing OCR models')
    monkeypatch.setattr(render_worker, 'recognize_selection', unavailable)
    result = render_worker.extract_selection_result(source, 0, [.12, .22], [.78, .27], allow_ocr=True)
    assert suspicious_text(result['text'])
    assert result['ocr_error'] == 'Missing OCR models'
    assert not result.get('ocr_used')


def test_blank_page_never_triggers_ocr(tmp_path, monkeypatch):
    source = tmp_path / 'blank.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    with source.open('wb') as output:
        writer.write(output)
    def unexpected(*args):
        pytest.fail('Empty selection should not trigger OCR')
    monkeypatch.setattr(render_worker, 'recognize_selection', unexpected)
    assert render_worker.extract_selection_result(source, 0, [.1, .1], [.9, .9], allow_ocr=True) == {'text': '', 'rects': []}


def test_worker_ocr_progress_and_result_protocol(tmp_path, monkeypatch):
    source = tmp_path / 'damaged.pdf'
    damaged_pdf(source)
    monkeypatch.setattr(render_worker, 'recognize_selection', lambda *args: 'Copy this text')
    request = {'type': 'copy_text', 'source': str(source), 'page': 0,
               'start': [.12, .22], 'end': [.78, .27], 'generation': 7, 'allow_ocr': True}
    output = io.StringIO()
    render_worker.serve(io.StringIO(json.dumps(request) + '\n'), output)
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [m['type'] for m in messages] == ['ready', 'ocr', 'text', 'done']
    assert messages[2]['text'] == 'Copy this text'
    assert messages[2]['ocr_used']


def test_rapidocr_recovers_damaged_mapping_offline(tmp_path, monkeypatch):
    from rapidocr.utils.download_file import DownloadFile
    def unexpected(*args, **kwargs):
        pytest.fail('OCR must use the bundled model without downloading')
    monkeypatch.setattr(DownloadFile, 'run', unexpected)
    source = tmp_path / 'damaged.pdf'
    damaged_pdf(source)
    result = render_worker.extract_selection_result(source, 0, [.12, .22], [.78, .27], allow_ocr=True)
    assert result.get('ocr_used'), result
    assert result['text'] == 'Copy this text'


def test_ocr_multiline_list_keeps_filename_underscores_and_markers(tmp_path):
    source = tmp_path / 'list.pdf'
    lines = ('Copy this text', ' - tkinter_basic.py: Tkinter',
             ' - tkinter_ttk.py: Tkinter.ttk',
             ' - customtkinter_demo.py: CustomTkinter',
             ' - pyside6_demo.py: PySide6', 'Common requirements:')
    damaged_pdf(source, lines=lines, point_size=9)
    result = render_worker.extract_selection_result(source, 0, [0, .18], [1, .45], allow_ocr=True)
    assert result.get('ocr_used'), result
    assert len(_line_regions(result['rects'])) == len(lines)
    recognized = result['text'].splitlines()
    assert len(recognized) == len(lines)
    for actual, expected in zip(recognized, lines):
        assert actual.replace(' ', '') == expected.replace(' ', '')


def test_ocr_clipboard_roundtrip_in_background(qtbot, tmp_path, monkeypatch):
    # An external OCR executable cannot be found by the background process.
    monkeypatch.setenv('PATH', '')
    source = tmp_path / 'damaged.pdf'
    damaged_pdf(source)
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
    window.copy_text_action.trigger()
    QApplication.clipboard().setText('before')
    window._copy_text_selection(doc, 0, card.preview, QPointF(36, 88), QPointF(234, 108), copy=False)
    qtbot.waitUntil(lambda: not window._text_requests, timeout=5000)
    assert QApplication.clipboard().text() == 'before'
    window._copy_text_selection(doc, 0, card.preview, QPointF(36, 88), QPointF(234, 108))
    qtbot.waitUntil(lambda: not window._text_requests, timeout=15000)
    assert QApplication.clipboard().text() == 'Copy this text'
    assert 'OCR' in window.statusBar().currentMessage()
    assert card.preview._highlight_rects


def test_low_confidence_ocr_preserves_original(tmp_path, monkeypatch):
    from repdf import ocr
    source = tmp_path / 'damaged.pdf'
    damaged_pdf(source)
    monkeypatch.setattr(ocr, '_engine', lambda: lambda image, **kwargs: SimpleNamespace(txts=('wrong',), scores=(0.4,)))
    result = render_worker.extract_selection_result(source, 0, [.12, .22], [.78, .27], allow_ocr=True)
    assert suspicious_text(result['text'])
    assert 'low confidence' in result['ocr_error']
    assert not result.get('ocr_used')


def test_missing_bundled_model_does_not_download(tmp_path, monkeypatch):
    from repdf import ocr
    ocr._engine.cache_clear()
    monkeypatch.setattr(ocr, 'find_spec', lambda name: SimpleNamespace(origin=str(tmp_path / '__init__.py')))
    with pytest.raises(OcrError, match='model is missing'):
        ocr._engine()
    ocr._engine.cache_clear()
