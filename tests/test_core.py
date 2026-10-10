from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from pdfpick.core import (
    InvalidPdfError,
    SelectionState,
    UnsupportedEncryptedPdfError,
    default_output_path,
    export_selected_pages,
    inspect_pdf,
    parity_state,
    set_parity,
    split_output_paths,
    split_selected_pages,
    DocumentSelection,
    export_documents,
    split_documents,
)


def make_pdf(path: Path, widths: list[int]) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=width + 100)
    with path.open("wb") as stream:
        writer.write(stream)


def test_parity_selection_and_state() -> None:
    selected = set_parity(set(), 5, odd=True, enabled=True)
    assert selected == {0, 2, 4}
    assert parity_state(selected, 5, True) is SelectionState.ALL
    assert parity_state(selected, 5, False) is SelectionState.NONE

    selected.remove(2)
    assert parity_state(selected, 5, True) is SelectionState.PARTIAL
    selected = set_parity(selected, 5, odd=True, enabled=False)
    assert selected == set()


def test_default_output_path() -> None:
    assert default_output_path(Path("report.pdf")) == Path("report_selected.pdf")


def test_export_preserves_source_order_and_page_sizes(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "selected.pdf"
    make_pdf(source, [200, 300, 400, 500])

    assert export_selected_pages(source, output, {3, 0, 2}) == 3
    reader = PdfReader(output)
    assert len(reader.pages) == 3
    assert [int(page.mediabox.width) for page in reader.pages] == [200, 400, 500]


def test_export_rejects_empty_selection_and_source_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, [200])
    with pytest.raises(ValueError, match="至少選取"):
        export_selected_pages(source, tmp_path / "out.pdf", set())
    with pytest.raises(ValueError, match="不可覆蓋"):
        export_selected_pages(source, source, {0})


def test_inspect_rejects_invalid_and_encrypted_pdf(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(InvalidPdfError):
        inspect_pdf(invalid)

    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with encrypted.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(UnsupportedEncryptedPdfError):
        inspect_pdf(encrypted)


def test_export_preserves_explicit_page_order(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "reordered.pdf"
    make_pdf(source, [200, 300, 400, 500])

    assert export_selected_pages(source, output, [3, 0, 2]) == 3
    reader = PdfReader(output)
    assert [int(page.mediabox.width) for page in reader.pages] == [500, 200, 400]


def test_split_preserves_order_and_pads_names(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, list(range(200, 212)))
    order = list(reversed(range(12)))
    outputs = split_selected_pages(source, tmp_path / "pages.pdf", order)
    assert [path.name for path in outputs] == [f"pages_{i:02d}.pdf" for i in range(1, 13)]
    for path, index in zip(outputs, order):
        reader = PdfReader(path)
        assert len(reader.pages) == 1
        assert int(reader.pages[0].mediabox.width) == 200 + index
    assert split_output_paths(tmp_path / "pages.pdf", 100)[0].name == "pages_001.pdf"


def test_split_rejects_source_overwrite_and_existing_outputs(tmp_path: Path) -> None:
    source = tmp_path / "pages_01.pdf"
    make_pdf(source, [200, 300])
    with pytest.raises(ValueError, match="不可覆蓋"):
        split_selected_pages(source, tmp_path / "pages.pdf", [0], overwrite=True)
    with pytest.raises(ValueError, match="至少選取"):
        split_selected_pages(source, tmp_path / "out.pdf", [])
    with pytest.raises(IndexError):
        split_selected_pages(source, tmp_path / "out.pdf", [0, 2])
    existing = tmp_path / "out_02.pdf"
    existing.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        split_selected_pages(source, tmp_path / "out.pdf", [1, 0])
    assert existing.read_bytes() == b"keep me"
    assert not (tmp_path / "out_01.pdf").exists()
    outputs = split_selected_pages(source, tmp_path / "out.pdf", [1, 0], overwrite=True)
    assert [int(PdfReader(path).pages[0].mediabox.width) for path in outputs] == [300, 200]


def test_split_generation_failure_leaves_outputs_untouched(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, [200, 300])
    existing = tmp_path / "out_01.pdf"
    existing.write_bytes(b"keep me")
    original_write = PdfWriter.write
    calls = 0

    def fail_second_write(writer, stream):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk error")
        return original_write(writer, stream)

    monkeypatch.setattr(PdfWriter, "write", fail_second_write)
    with pytest.raises(OSError, match="disk error"):
        split_selected_pages(source, tmp_path / "out.pdf", [0, 1], overwrite=True)
    assert existing.read_bytes() == b"keep me"
    assert not (tmp_path / "out_02.pdf").exists()
    assert not list(tmp_path.glob(".pdfpick-split-*"))


def test_multi_document_export_order_and_metadata(tmp_path) -> None:
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    for path, widths, title in ((a, [200, 300], "A"), (b, [400, 500], "B")):
        writer = PdfWriter()
        writer.add_metadata({"/Title": title})
        for width in widths:
            writer.add_blank_page(width=width, height=600)
        with path.open("wb") as stream:
            writer.write(stream)
    selections = [DocumentSelection(b, (1, 0)), DocumentSelection(a, (1,))]
    merged = tmp_path / "merged.pdf"
    assert export_documents(selections, merged) == 3
    reader = PdfReader(merged)
    assert [int(page.mediabox.width) for page in reader.pages] == [500, 400, 300]
    assert reader.metadata.title == "B"
    outputs = split_documents(selections, tmp_path / "single.pdf")
    assert [path.name for path in outputs] == ["single_01.pdf", "single_02.pdf", "single_03.pdf"]
    assert [int(PdfReader(path).pages[0].mediabox.width) for path in outputs] == [500, 400, 300]
    assert [PdfReader(path).metadata.title for path in outputs] == ["B", "B", "A"]


def test_multi_document_validates_all_sources_before_writing(tmp_path) -> None:
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    make_pdf(a, [200])
    make_pdf(b, [300])
    selected = [DocumentSelection(a, (0,)), DocumentSelection(b, (2,))]
    existing = tmp_path / "out.pdf"
    existing.write_bytes(b"keep")
    with pytest.raises(IndexError):
        export_documents(selected, existing)
    assert existing.read_bytes() == b"keep"
    with pytest.raises(ValueError, match="不可覆蓋"):
        export_documents([DocumentSelection(a, (0,))], b, protected_sources=(b,))
    with pytest.raises(ValueError, match="不可覆蓋"):
        split_documents([DocumentSelection(a, (0,))], tmp_path / "x.pdf",
                        protected_sources=(tmp_path / "x_01.pdf",))


def test_multi_document_reads_each_source_once(tmp_path, monkeypatch) -> None:
    import pdfpick.core as core
    source = tmp_path / "source.pdf"
    make_pdf(source, [200, 300])
    calls = []
    original = core.PdfReader
    monkeypatch.setattr(core, "PdfReader", lambda path: (calls.append(path), original(path))[1])
    output = tmp_path / "out.pdf"
    export_documents([DocumentSelection(source, (1,)), DocumentSelection(source, (0,))], output)
    assert calls == [source]
    assert [int(page.mediabox.width) for page in PdfReader(output).pages] == [300, 200]
