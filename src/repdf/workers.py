from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from repdf.core import DocumentSelection, export_documents, inspect_pdf, split_documents


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
        self, documents: list[DocumentSelection], destination: Path, session_id: int,
        *, split: bool = False, overwrite: bool = False, protected_sources: tuple[Path, ...] = (),
    ) -> None:
        super().__init__()
        self.documents = tuple(DocumentSelection(item.source, tuple(item.pages)) for item in documents)
        self.destination = destination
        self.session_id = session_id
        self.signals = ExportSignals()
        self.split = split
        self.overwrite = overwrite
        self.protected_sources = protected_sources

    @Slot()
    def run(self) -> None:
        try:
            if self.split:
                count = len(split_documents(self.documents, self.destination,
                                            overwrite=self.overwrite, protected_sources=self.protected_sources))
            else:
                count = export_documents(self.documents, self.destination,
                                         protected_sources=self.protected_sources)
            self.signals.completed.emit(self.session_id, self.destination, count)
        except Exception as exc:
            self.signals.failed.emit(self.session_id, str(exc))
