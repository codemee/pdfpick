from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import TextIO

import pypdfium2 as pdfium


def render_document(
    source: Path, scale: float, output_dir: Path, generation: int,
    output_stream: TextIO | None = None,
) -> None:
    document = pdfium.PdfDocument(str(source))
    try:
        for page_index in range(len(document)):
            page = document[page_index]
            try:
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
            }), file=output_stream, flush=True)
    finally:
        document.close()


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
            render_document(
                Path(request["source"]), float(request["scale"]),
                Path(request["output_dir"]), int(request["generation"]), output_stream,
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
