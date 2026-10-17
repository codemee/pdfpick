"""Optional, local OCR fallback for damaged PDF text mappings."""
from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path

from PIL import ImageOps


class OcrError(RuntimeError):
    pass


def _clean_line(text: str) -> str:
    # Remove OCR segmentation spaces within CJK text; keep English word spaces.
    cjk = r'\u3400-\u9fff\uf900-\ufaff\U00020000-\U000323af'
    return re.sub(fr'(?<=[{cjk}]) +(?=[{cjk}])', '', text.strip())


def suspicious_text(text: str) -> bool:
    """Only flag explicit corruption; valid CJK, ligatures and private-use stay intact."""
    return any(char == '\ufffd' or 0xFDD0 <= ord(char) <= 0xFDEF
               or ord(char) & 0xFFFF in (0xFFFE, 0xFFFF) or unicodedata.category(char) == 'Cs'
               or (unicodedata.category(char) == 'Cc' and char not in '\r\n\t')
               for char in text)


MODEL_NAME = 'PP-OCRv6_rec_small.onnx'
MODEL_SHA256 = '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'


@lru_cache(maxsize=1)
def _engine():
    """Load only on first damaged selection, in the existing background process."""
    try:
        spec = find_spec('rapidocr')
        if spec is None or spec.origin is None:
            raise OcrError('RapidOCR is not installed. Run uv sync.')
        model = Path(spec.origin).parent / 'models' / MODEL_NAME
        if not model.is_file():
            raise OcrError('Bundled OCR model is missing. Reinstall RapidOCR 3.10.0.')
        if hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
            raise OcrError('Bundled OCR model checksum mismatch.')
        from rapidocr import RapidOCR
        engine = RapidOCR(params={
            'Global.use_det': False,
            'Global.use_cls': False,
            'Global.use_preprocess_img': False,
            'Global.log_level': 'error',
            'Rec.model_path': str(model),  # Explicit local path disables model downloads.
            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        })
        return engine
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f'Cannot initialize RapidOCR: {exc}') from exc


def _line_regions(rects: list[list[float]]) -> list[list[float]]:
    """Keep selected glyph order and avoid including unselected line beginnings/ends."""
    lines: list[list[float]] = []
    for left, top, right, bottom in rects:
        if lines:
            previous = lines[-1]
            overlap = min(bottom, previous[3]) - max(top, previous[1])
            same_line = overlap > 0.4 * min(bottom - top, previous[3] - previous[1])
            if same_line:
                previous[:] = [min(left, previous[0]), min(top, previous[1]),
                               max(right, previous[2]), max(bottom, previous[3])]
                continue
        lines.append([left, top, right, bottom])
    return lines


def recognize_selection(page, rects: list[list[float]]) -> str:
    """Render selected glyphs at 400 DPI; do not OCR arbitrary/image-only regions."""
    if not rects:
        raise OcrError('No selected text bounds are available.')
    width, height = page.get_size()
    scale = 400 / 72
    lines = _line_regions(rects)
    if len(lines) > 30:
        raise OcrError('Please select at most 30 lines for OCR.')
    engine = _engine()
    output = []
    deadline = time.monotonic() + 60
    for left, top, right, bottom in lines:
        # Small padding preserves antialiased glyph edges without adding neighbours.
        x0, y0 = max(0, left * width - 0.5), max(0, top * height - 0.5)
        x1, y1 = min(width, right * width + 0.5), min(height, bottom * height + 0.5)
        if (x1 - x0) * (y1 - y0) * scale ** 2 > 20_000_000:
            raise OcrError('Selected OCR region is too large.')
        bitmap = page.render(scale=scale, crop=(x0, height - y1, width - x1, y0))
        try:
            image = ImageOps.expand(bitmap.to_pil().convert('RGB'), border=2, fill='white')
        finally:
            bitmap.close()
        if time.monotonic() >= deadline:
            raise OcrError('OCR time limit reached.')
        try:
            result = engine(image)
        except Exception as exc:
            raise OcrError(f'RapidOCR failed: {exc}') from exc
        if not result.txts or not result.scores:
            raise OcrError('OCR did not return usable text.')
        text = result.txts[0].strip()
        if not text or suspicious_text(text) or min(result.scores) < 0.8:
            raise OcrError('OCR result is empty, damaged or low confidence.')
        output.append(_clean_line(text))
    return '\n'.join(output)
