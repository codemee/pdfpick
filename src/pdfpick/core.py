from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader, PdfWriter


class PdfPickError(Exception):
    """Base error presented to the user."""


class UnsupportedEncryptedPdfError(PdfPickError):
    """Raised when a PDF requires a password."""


class InvalidPdfError(PdfPickError):
    """Raised when a PDF cannot be parsed."""


class SelectionState(Enum):
    NONE = 0
    PARTIAL = 1
    ALL = 2


@dataclass(frozen=True)
class PdfInfo:
    path: Path
    page_count: int


@dataclass(frozen=True)
class DocumentSelection:
    source: Path
    pages: tuple[int, ...]


def _prepare_documents(documents: Iterable[DocumentSelection]):
    prepared = []
    readers = {}
    for document in documents:
        if not document.pages:
            continue
        source = Path(document.source).resolve()
        if source not in readers:
            if not source.is_file():
                raise FileNotFoundError(f"找不到來源 PDF 檔案：{source}")
            readers[source] = PdfReader(source)
        reader = readers[source]
        if reader.is_encrypted:
            raise UnsupportedEncryptedPdfError(f"目前不支援密碼保護的 PDF：{source}")
        if any(page < 0 or page >= len(reader.pages) for page in document.pages):
            raise IndexError(f"選取的頁碼超出來源 PDF 範圍：{source}")
        prepared.append((source, reader, document.pages))
    if not prepared:
        raise ValueError("請至少選取一頁。")
    return prepared


def _copy_metadata(reader: PdfReader, writer: PdfWriter) -> None:
    if reader.metadata:
        writer.add_metadata({str(key): str(value) for key, value in reader.metadata.items()
                             if key and value is not None})


def indices_for_parity(page_count: int, odd: bool) -> set[int]:
    """Return zero-based indices for human-facing odd or even page numbers."""
    start = 0 if odd else 1
    return set(range(start, page_count, 2))


def parity_state(selected: set[int], page_count: int, odd: bool) -> SelectionState:
    group = indices_for_parity(page_count, odd)
    if not group or not (selected & group):
        return SelectionState.NONE
    if group <= selected:
        return SelectionState.ALL
    return SelectionState.PARTIAL


def set_parity(
    selected: set[int], page_count: int, odd: bool, enabled: bool
) -> set[int]:
    result = set(selected)
    group = indices_for_parity(page_count, odd)
    if enabled:
        result.update(group)
    else:
        result.difference_update(group)
    return result


def default_output_path(source: str | Path) -> Path:
    path = Path(source)
    return path.with_name(f"{path.stem}_selected.pdf")


def split_output_paths(destination: str | Path, count: int) -> list[Path]:
    path = Path(destination)
    digits = max(2, len(str(count)))
    return [path.with_name(f"{path.stem}_{number:0{digits}d}.pdf")
            for number in range(1, count + 1)]


def split_selected_pages(
    source: str | Path, destination: str | Path, selected: Iterable[int], *,
    overwrite: bool = False,
) -> list[Path]:
    ordered = sorted(selected) if isinstance(selected, (set, frozenset)) else list(dict.fromkeys(selected))
    return split_documents([DocumentSelection(Path(source), tuple(ordered))], destination,
                           overwrite=overwrite)


def split_documents(
    documents: Iterable[DocumentSelection], destination: str | Path, *,
    overwrite: bool = False, protected_sources: Iterable[Path] = (),
) -> list[Path]:
    prepared = _prepare_documents(documents)
    outputs = split_output_paths(Path(destination).resolve(), sum(len(pages) for _, _, pages in prepared))
    protected = {source for source, _, _ in prepared} | {Path(path).resolve() for path in protected_sources}
    if protected.intersection(outputs):
        raise ValueError("輸出檔案不可覆蓋來源 PDF。")
    if not overwrite and any(path.exists() for path in outputs):
        raise FileExistsError("部分單頁檔案已存在，請確認覆蓋或更換檔名。")
    outputs[0].parent.mkdir(parents=True, exist_ok=True)
    # Finish generating every page before publishing any output file.
    with tempfile.TemporaryDirectory(prefix=".pdfpick-split-", dir=outputs[0].parent) as staging:
        staged = []
        ordered = [(reader, page) for _, reader, pages in prepared for page in pages]
        for (reader, page), output in zip(ordered, outputs):
            writer = PdfWriter()
            writer.add_page(reader.pages[page])
            _copy_metadata(reader, writer)
            pending = Path(staging) / output.name
            with pending.open("wb") as stream:
                writer.write(stream)
                stream.flush()
                os.fsync(stream.fileno())
            staged.append(pending)
        published = 0
        try:
            for pending, output in zip(staged, outputs):
                if overwrite:
                    os.replace(pending, output)
                elif os.name == "nt":
                    # Windows rename is atomic and refuses an existing destination.
                    os.rename(pending, output)
                else:
                    # Exclusive publication also protects against files created during export.
                    os.link(pending, output)
                published += 1
        except OSError as exc:
            raise OSError(f"拆分輸出失敗；已完成 {published} / {len(outputs)} 個檔案。\n{exc}") from exc
    return outputs


def inspect_pdf(source: str | Path) -> PdfInfo:
    path = Path(source).resolve()
    if not path.is_file():
        raise InvalidPdfError("找不到來源 PDF 檔案。")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise UnsupportedEncryptedPdfError("目前不支援密碼保護的 PDF。")
        page_count = len(reader.pages)
    except UnsupportedEncryptedPdfError:
        raise
    except Exception as exc:
        raise InvalidPdfError("無法讀取這個 PDF，檔案可能已損壞或格式不受支援。") from exc
    if page_count == 0:
        raise InvalidPdfError("這個 PDF 沒有可用的頁面。")
    return PdfInfo(path=path, page_count=page_count)


def export_selected_pages(
    source: str | Path, destination: str | Path, selected: Iterable[int]
) -> int:
    ordered = (
        sorted(selected) if isinstance(selected, (set, frozenset))
        else list(dict.fromkeys(selected))
    )
    return export_documents([DocumentSelection(Path(source), tuple(ordered))], destination)


def export_documents(
    documents: Iterable[DocumentSelection], destination: str | Path, *,
    protected_sources: Iterable[Path] = (),
) -> int:
    prepared = _prepare_documents(documents)
    destination_path = Path(destination).resolve()
    protected = {source for source, _, _ in prepared} | {Path(path).resolve() for path in protected_sources}
    if destination_path in protected:
        raise ValueError("輸出檔案不可覆蓋來源 PDF。")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        writer = PdfWriter()
        for _, reader, pages in prepared:
            for page_index in pages:
                writer.add_page(reader.pages[page_index])
        _copy_metadata(prepared[0][1], writer)

        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".pdf", prefix=".pdfpick-", dir=destination_path.parent,
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            writer.write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination_path)
        temp_path = None
        return sum(len(pages) for _, _, pages in prepared)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
