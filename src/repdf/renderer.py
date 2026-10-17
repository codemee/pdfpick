from __future__ import annotations

from repdf.strings import tr

import json
import secrets
import socket
import subprocess
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import TextIO

from PySide6.QtCore import QObject, Signal


def start_render_backend() -> subprocess.Popen[str]:
    if getattr(sys, "frozen", False):
        return _start_frozen_backend()
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [sys.executable, "-m", "repdf.render_worker", "--server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
        creationflags=creation_flags,
    )
    assert process.stdout is not None
    ready_line = process.stdout.readline()
    try:
        ready = json.loads(ready_line)
    except json.JSONDecodeError as exc:
        process.terminate()
        raise RuntimeError(tr('無法啟動 PDF 預覽後端。')) from exc
    if ready.get("type") != "ready":
        process.terminate()
        raise RuntimeError(tr('PDF 預覽後端未正確啟動。'))
    return process


def _start_frozen_backend() -> subprocess.Popen[str]:
    # Windowed executables have no stdin/stdout; use an authenticated local socket.
    token = secrets.token_hex(32)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(30)
        port = listener.getsockname()[1]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = subprocess.Popen(
            [sys.executable, "--render-server", str(port), token],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        try:
            connection, _address = listener.accept()
            with connection:
                connection.settimeout(30)
                process.stdin = connection.makefile("w", encoding="utf-8")
                process.stdout = connection.makefile("r", encoding="utf-8")
                ready = json.loads(process.stdout.readline())
                if ready.get("type") != "ready" or ready.get("token") != token:
                    raise RuntimeError(tr('PDF 預覽後端驗證失敗。'))
                connection.settimeout(None)
            return process
        except Exception as exc:
            process.terminate()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
            raise RuntimeError(tr('無法啟動封裝版 PDF 預覽後端。')) from exc


class RenderService(QObject):
    message = Signal(object)

    def __init__(self, process: subprocess.Popen[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.process = process
        self._lock = threading.Lock()
        self._busy = False
        self._pending: OrderedDict[int, dict[str, object]] = OrderedDict()
        self._closed = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def request(
        self, source: Path, scale: float, output_dir: Path, generation: int,
        *, document_id: int = 0, pages: list[int] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "source": str(source),
            "scale": scale,
            "output_dir": str(output_dir),
            "generation": generation,
        }
        if pages is not None:
            payload["pages"] = list(pages)
        with self._lock:
            if self._closed:
                return
            self._pending[document_id] = payload
            self._pending.move_to_end(document_id, last=False)
            self._start_next()

    def request_text(self, source: Path, page: int, start: tuple[float, float],
                     end: tuple[float, float], generation: int, document_id: int,
                     *, allow_ocr: bool = False) -> None:
        payload: dict[str, object] = {
            "type": "copy_text", "source": str(source), "page": page,
            "start": start, "end": end, "generation": generation,
            "allow_ocr": allow_ocr,
        }
        with self._lock:
            if self._closed:
                return
            self._pending[document_id] = payload
            self._pending.move_to_end(document_id, last=False)
            self._start_next()

    def cancel_pending(self, document_id: int) -> None:
        with self._lock:
            self._pending.pop(document_id, None)

    def prioritize(self, document_id: int) -> None:
        with self._lock:
            if document_id in self._pending:
                self._pending.move_to_end(document_id, last=False)

    def _start_next(self) -> None:
        while self._pending and not self._busy and not self._closed:
            _, payload = self._pending.popitem(last=False)
            self._busy = self._write(payload)

    def _write(self, payload: dict[str, object]) -> bool:
        stream = self.process.stdin
        if stream is None or self.process.poll() is not None:
            self.message.emit({
                "type": "error", "generation": payload["generation"],
                "message": tr('PDF 預覽後端已停止。'),
            })
            return False
        try:
            stream.write(json.dumps(payload) + "\n")
            stream.flush()
            return True
        except (OSError, ValueError) as exc:
            self.message.emit({"type": "error", "generation": payload["generation"],
                               "message": str(exc)})
            return False

    def _read_loop(self) -> None:
        stream: TextIO | None = self.process.stdout
        if stream is None:
            return
        for line in stream:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.message.emit(payload)
            if payload.get("type") in {"done", "error"}:
                with self._lock:
                    self._busy = False
                    self._start_next()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending.clear()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()
