from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import TextIO

import pypdfium2 as pdfium

from repdf.ocr import OcrError, recognize_selection, suspicious_text


def render_document(
    source: Path, scale: float, output_dir: Path, generation: int,
    output_stream: TextIO | None = None,
    pages: list[int] | None = None,
) -> None:
    document = pdfium.PdfDocument(str(source))
    try:
        indices = range(len(document)) if pages is None else pages
        for page_index in indices:
            if not isinstance(page_index, int) or not 0 <= page_index < len(document):
                raise ValueError("Invalid preview page index")
            page = document[page_index]
            try:
                width_points, height_points = page.get_size()
                bitmap = page.render(scale=max(scale, 0.1))
                try:
                    image = bitmap.to_pil().convert("RGB")
                    output = output_dir / f"g{generation}-p{page_index}.png"
                    image.save(output, "PNG")
                finally:
                    bitmap.close()
            finally:
                page.close()
            print(json.dumps({
                "type": "page", "generation": generation,
                "page": page_index, "path": str(output),
                "width_points": width_points, "height_points": height_points,
            }), file=output_stream, flush=True)
    finally:
        document.close()


def extract_selection_result(source: Path, page_index: int, start: list[float],
                             end: list[float], *, allow_ocr: bool = False,
                             on_ocr=None) -> dict[str, object]:
    """Return copied text and the matching glyph bounds in rendered-page coordinates."""
    document = pdfium.PdfDocument(str(source))
    try:
        if not 0 <= page_index < len(document):
            raise ValueError("Invalid text selection page index")
        page = document[page_index]
        try:
            left, bottom, right, top = page.get_bbox()
            rotation = page.get_rotation()
            width, height = right - left, top - bottom

            def canvas(position):
                if len(position) != 2:
                    raise ValueError("Invalid text selection position")
                x, y = (min(1, max(0, float(value))) for value in position)
                if rotation == 90:
                    return left + y * width, bottom + x * height
                if rotation == 180:
                    return right - x * width, bottom + y * height
                if rotation == 270:
                    return right - y * width, top - x * height
                return left + x * width, top - y * height

            def normalized(x, y):
                if rotation == 90:
                    return (y - bottom) / height, (x - left) / width
                if rotation == 180:
                    return (right - x) / width, (y - bottom) / height
                if rotation == 270:
                    return (top - y) / height, (right - x) / width
                return (x - left) / width, (top - y) / height

            x1, y1 = canvas(start)
            x2, y2 = canvas(end)
            textpage = page.get_textpage()
            try:
                first = textpage.get_index(x1, y1, 8, 8)
                last = textpage.get_index(x2, y2, 8, 8)
                if first is not None and last is not None:
                    lo, hi = sorted((first, last))
                    text = textpage.get_text_range(lo, hi - lo + 1)
                else:
                    # Include glyph height around a thin or rotated drag.
                    bounds = (min(x1, x2) - 8, min(y1, y2) - 18,
                              max(x1, x2) + 8, max(y1, y2) + 18)
                    hits = []
                    for index in range(textpage.count_chars()):
                        box = textpage.get_charbox(index)
                        if box and box[0] <= bounds[2] and box[2] >= bounds[0] and box[1] <= bounds[3] and box[3] >= bounds[1]:
                            hits.append(index)
                    if not hits:
                        return {"text": "", "rects": []}
                    lo, hi = hits[0], hits[-1]
                    text = textpage.get_text_range(lo, hi - lo + 1)

                rects = []
                if text:
                    for index in range(lo, hi + 1):
                        box = textpage.get_charbox(index)
                        if not box or box[2] <= box[0] or box[3] <= box[1]:
                            continue
                        corners = [normalized(x, y) for x in (box[0], box[2])
                                   for y in (box[1], box[3])]
                        xs, ys = zip(*corners)
                        rects.append([min(xs), min(ys), max(xs), max(ys)])
                result = {"text": text, "rects": rects}
                if allow_ocr and text and suspicious_text(text):
                    if on_ocr is not None:
                        on_ocr()
                    try:
                        result['text'] = recognize_selection(page, rects)
                        result['ocr_used'] = True
                    except OcrError as exc:
                        result['ocr_error'] = str(exc)
                return result
            finally:
                textpage.close()
        finally:
            page.close()
    finally:
        document.close()


def extract_selection(source: Path, page_index: int, start: list[float], end: list[float]) -> str:
    return str(extract_selection_result(source, page_index, start, end)["text"])


def serve(
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
    token: str | None = None,
) -> int:
    input_stream = input_stream if input_stream is not None else sys.stdin
    output_stream = output_stream if output_stream is not None else sys.stdout
    ready = {"type": "ready"}
    if token is not None:
        ready["token"] = token
    print(json.dumps(ready), file=output_stream, flush=True)
    for line in input_stream:
        request: dict[str, object] = {}
        try:
            request = json.loads(line)
            if request.get("type") == "copy_text":
                extracted = extract_selection_result(Path(request["source"]), int(request["page"]),
                    request["start"], request["end"], allow_ocr=bool(request.get('allow_ocr', False)),
                    on_ocr=lambda: print(json.dumps({'type': 'ocr', 'generation': int(request['generation'])}),
                                         file=output_stream, flush=True))
                print(json.dumps({"type": "text", "generation": int(request["generation"]),
                                  **extracted}), file=output_stream, flush=True)
            else:
                render_document(
                    Path(request["source"]), float(request["scale"]),
                    Path(request["output_dir"]), int(request["generation"]), output_stream,
                    pages=request.get("pages"),
                )
            print(json.dumps({
                "type": "done", "generation": int(request["generation"]),
            }), file=output_stream, flush=True)
        except Exception as exc:
            print(json.dumps({
                "type": "error",
                "generation": request.get("generation", -1) if isinstance(request, dict) else -1,
                "message": str(exc),
            }), file=output_stream, flush=True)
    return 0


def serve_socket(port: int, token: str) -> int:
    with socket.create_connection(("127.0.0.1", port), timeout=30) as connection:
        connection.settimeout(None)
        with connection.makefile("r", encoding="utf-8") as reader:
            with connection.makefile("w", encoding="utf-8") as writer:
                return serve(reader, writer, token)


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--server":
        return serve()
    if len(sys.argv) != 5:
        print("invalid render worker arguments", file=sys.stderr)
        return 2
    try:
        render_document(
            Path(sys.argv[1]), float(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4])
        )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
