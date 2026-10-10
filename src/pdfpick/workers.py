from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from pdfpick.core import export_selected_pages, inspect_pdf, split_selected_pages


class LoadSignals(QObject):
    loaded = Signal(int, object, int)
    failed = Signal(int, str)


class LoadPdfTask(QRunnable):
    def __init__(self, source: Path, session_id: int) -> None:
        super().__init__()
        self.source = source
        self.session_id = session_id
        self.signals = LoadSignals()

    @Slot()
    def run(self) -> None:
        try:
            info = inspect_pdf(self.source)
            self.signals.loaded.emit(self.session_id, info.path, info.page_count)
        except Exception as exc:
            self.signals.failed.emit(self.session_id, str(exc))


class ExportSignals(QObject):
    completed = Signal(int, object, int)
    failed = Signal(int, str)


class ExportPdfTask(QRunnable):
    def __init__(
        self, source: Path, destination: Path, selected: list[int], session_id: int,
        *, split: bool = False, overwrite: bool = False,
    ) -> None:
        super().__init__()
        self.source = source
        self.destination = destination
        self.selected = list(selected)
        self.session_id = session_id
        self.signals = ExportSignals()
        self.split = split
        self.overwrite = overwrite

    @Slot()
    def run(self) -> None:
        try:
            if self.split:
                count = len(split_selected_pages(self.source, self.destination, self.selected,
                                                 overwrite=self.overwrite))
            else:
                count = export_selected_pages(self.source, self.destination, self.selected)
            self.signals.completed.emit(self.session_id, self.destination, count)
        except Exception as exc:
            self.signals.failed.emit(self.session_id, str(exc))
