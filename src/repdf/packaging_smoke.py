from __future__ import annotations

import json
import os
import tempfile
import traceback
from pathlib import Path


def main(report_path: str) -> int:
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication
        from pypdf import PdfReader, PdfWriter
        from repdf import __version__
        from repdf.app import load_app_icon
        from repdf.core import DocumentSelection, export_selected_pages, export_documents, split_documents
        from repdf.renderer import start_render_backend
        from repdf.preferences import LanguageController
        from repdf.strings import tr
        from repdf.theme import ThemeController
        from repdf.ocr import _engine
        from PIL import Image, ImageDraw, ImageFont
        app = QApplication([])
        language = LanguageController("zh")
        if language.qt_translator.isEmpty():
            raise RuntimeError("Traditional Chinese dialog translations are missing")
        language.set_mode("en")
        if tr("第 {p0} 頁", p0=1) != "Page 1":
            raise RuntimeError("English translation failed")
        theme = ThemeController(app, "light")
        theme.set_mode("dark")
        language.close()
        if load_app_icon().isNull():
            raise RuntimeError("Application icon is missing")
        ocr_image = Image.new('RGB', (500, 100), 'white')
        ImageDraw.Draw(ocr_image).text((15, 15), 'Copy this text',
                                     font=ImageFont.load_default(size=48), fill='black')
        ocr_result = _engine()(ocr_image)
        if not ocr_result.txts or ocr_result.txts[0] != 'Copy this text':
            raise RuntimeError(f"Packaged OCR failed: {ocr_result.txts}")
        with tempfile.TemporaryDirectory(prefix="repdf-smoke-") as directory:
            root = Path(directory)
            source = root / "source.pdf"
            writer = PdfWriter()
            for width in (200, 300):
                writer.add_blank_page(width=width, height=400)
            with source.open("wb") as stream:
                writer.write(stream)
            process = start_render_backend()
            process.stdin.write(json.dumps({
                "source": str(source), "output_dir": str(root),
                "scale": 0.5, "generation": 1,
            }) + "\n")
            process.stdin.flush()
            pages = []
            for line in process.stdout:
                message = json.loads(line)
                if message["type"] == "error":
                    raise RuntimeError(message["message"])
                if message["type"] == "page":
                    if QImage(message["path"]).isNull():
                        raise RuntimeError("Invalid rendered page")
                    pages.append(message["page"])
                if message["type"] == "done":
                    break
            if pages != [0, 1]:
                raise RuntimeError(f"Unexpected rendered pages: {pages}")
            output = root / "reordered.pdf"
            export_selected_pages(source, output, [1, 0])
            if [int(page.mediabox.width) for page in PdfReader(output).pages] != [300, 200]:
                raise RuntimeError("Reordered export failed")
            second = root / "second.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=400, height=500)
            with second.open("wb") as stream:
                writer.write(stream)
            selections = [DocumentSelection(second, (0,)), DocumentSelection(source, (1, 0))]
            merged = root / "multi.pdf"
            export_documents(selections, merged)
            if [int(page.mediabox.width) for page in PdfReader(merged).pages] != [400, 300, 200]:
                raise RuntimeError("Multi-document export failed")
            single_pages = split_documents(selections, root / "single.pdf")
            if [int(PdfReader(path).pages[0].mediabox.width) for path in single_pages] != [400, 300, 200]:
                raise RuntimeError("Multi-document split failed")
        report.write_text(json.dumps({"ok": True, "version": __version__,
                                      "ocr_engine": "RapidOCR/ONNX Runtime",
                                      "ocr_text": ocr_result.txts[0]}), encoding="utf-8")
        return 0
    except Exception:
        report.write_text(json.dumps({"ok": False, "error": traceback.format_exc()}), encoding="utf-8")
        return 1
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
