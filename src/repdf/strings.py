"""UI translations shared by the GUI and background error messages."""

import re
from string import Formatter

LANGUAGE = "zh"
ENGLISH = {
    "全螢幕單頁": "Fullscreen single page",
    "全螢幕對頁": "Fullscreen facing pages",
    "全螢幕封面＋對頁": "Fullscreen cover and facing pages",
    "全螢幕單頁（F11）；Esc 結束，方向鍵／Page Up／Page Down 切頁，可勾選頁面": "Fullscreen single page (F11); Esc to exit, arrows / Page Up / Page Down to navigate; check pages to select",
    "全螢幕對頁：依目前順序兩頁並排；Esc 結束，方向鍵／Page Up／Page Down 切頁，可勾選頁面": "Fullscreen facing pages: two pages in current order; Esc to exit, arrows / Page Up / Page Down to navigate; check pages to select",
    "全螢幕封面＋對頁：第一頁單獨顯示，其餘兩頁並排；Esc 結束，方向鍵／Page Up／Page Down 切頁，可勾選頁面": "Fullscreen cover and facing pages: first page alone, then pairs; Esc to exit, arrows / Page Up / Page Down to navigate; check pages to select",
    "Fit：將目前單頁等比例縮放至預覽區，視窗調整時自動適應": "Fit: scale the current page to fit the preview area; adapt when the window is resized",
    "複製文字": "Copy text",
    "下一個標籤頁": "Next tab",
    "上一個標籤頁": "Previous tab",
    "複製文字：點擊切換；啟用後在頁面拖曳選取文字並複製到剪貼簿，停用後恢復拖放排序。掃描影像中的文字需先經過 OCR。": "Copy text: click to toggle. Drag across a page to select text and copy it to the clipboard; turn off to restore page reordering. Scanned images need OCR first.",
    "拖曳選取文字並複製到剪貼簿": "Drag to select text and copy it to the clipboard",
    "文字複製模式中無法拖放頁面": "Page dragging is unavailable in text-copy mode",
    "正在擷取文字…": "Extracting text…",
    "區域 OCR": "Region OCR",
    "區域 OCR：框選頁面或圖片中的區域，放開滑鼠後辨識並複製文字。": "Region OCR: drag a rectangle on a page or image; release to recognize and copy text.",
    "框選區域並以 OCR 複製文字": "Drag a region to recognize and copy text with OCR",
    "正在辨識選取區域…": "Recognizing selected region…",
    "選取文字疑似損壞，正在進行 OCR…": "Selected text appears damaged. Running OCR…",
    "OCR 未完成，已複製原始文字：{p0}": "OCR failed; copied original text: {p0}",
    "已透過 OCR 複製 {p0} 個字元，請確認辨識結果": "Copied {p0} characters using OCR; please check the result",
    "已複製 {p0} 個字元到剪貼簿": "Copied {p0} characters to the clipboard",
    "選取範圍沒有可複製的文字": "No copyable text in the selected area",
    "無法擷取文字：{p0}": "Could not extract text: {p0}",
    "全螢幕預覽": "Fullscreen preview",
    "全螢幕單頁預覽（F11）；Esc 結束，左右方向鍵切換頁面": "Fullscreen page preview (F11); Esc to exit, arrow keys to change pages",
    "勾選此檔案以加入重組或拆分；未勾選任何標籤時僅輸出目前檔案": "Include this file in merge or split; if no tabs are checked, use only the current file",
    "關閉此檔案": "Close this file",
    "關閉此檔案（{p0}）": "Close this file ({p0})",
    "關閉目前標籤頁": "Close current tab",
    "關閉目前標籤頁（{p0}）": "Close current tab ({p0})",
    "正在讀取 PDF…": "Reading PDF…",
    "已調整第 {p0} 頁的預覽與輸出順序": "Updated the preview and output order of page {p0}",
    "正在產生頁面預覽…": "Rendering page previews…",
    "已載入 {p0} 頁；已選取 {p1} 頁": "Loaded {p0} pages; {p1} selected",
    "部分頁面無法產生預覽": "Some page previews could not be rendered",
    "預覽失敗": "Preview failed",
    "無法完成頁面預覽：\n{p0}": "Could not render page previews:\n{p0}",
    "請先開啟 PDF 檔案，或將多個 PDF 拖曳到視窗": "Open PDF files, or drag PDFs into this window",
    "就緒": "Ready",
    "檔案與顯示": "Files and display",
    "開啟 PDF": "Open PDF",
    "開啟 PDF（Ctrl+O）": "Open PDF (Ctrl+O)",
    "輸出選取頁面": "Merge selected pages",
    "輸出選取頁面為新 PDF（Ctrl+S / Ctrl+Shift+S）": "Merge selected pages into a new PDF (Ctrl+S / Ctrl+Shift+S)",
    "拆分選取頁面": "Split selected pages",
    "拆分選取頁面：依目前順序存成單頁 PDF，檔名附加補零序號": "Split selected pages into individual PDFs in the current order, with zero-padded file numbers",
    "單數頁": "Odd pages",
    "雙數頁": "Even pages",
    "選取或取消原始頁碼的單數頁": "Select or deselect odd source page numbers in the current tab",
    "選取或取消原始頁碼的雙數頁": "Select or deselect even source page numbers in the current tab",
    "縮小": "Zoom out",
    "縮小（Ctrl+-）": "Zoom out (Ctrl+-)",
    "頁面顯示比例": "Page zoom",
    "100% 以 96 DPI 顯示 PDF 頁面": "100% displays PDF pages at 96 DPI",
    "放大": "Zoom in",
    "放大（Ctrl++ / Ctrl+=）": "Zoom in (Ctrl++ / Ctrl+=)",
    "頁面顯示比例：25%–200%\n拖曳右側滑桿調整比例。\n放大：Ctrl++ 或 Ctrl+=（每次增加 25 個百分點）\n縮小：Ctrl+-（每次減少 25 個百分點）\n回到 100%：點擊比例或按 Ctrl+0\n100% 以 96 DPI 顯示 PDF 頁面。": "Page zoom: 25%–200%\nDrag the slider on the right to adjust zoom.\nZoom in: Ctrl++ or Ctrl+= (25 percentage points per step)\nZoom out: Ctrl+- (25 percentage points per step)\nReset to 100%: click the percentage or press Ctrl+0\n100% displays PDF pages at 96 DPI.",
    "目前檔案：已選取 {p0} / {p1} 頁；輸出合計 {p2} 頁": "Current file: {p0} / {p1} pages selected; {p2} pages in output",
    "PDF 檔案 (*.pdf)": "PDF files (*.pdf)",
    "部分 PDF 無法開啟": "Some PDFs could not be opened",
    "拆分選取頁面：指定檔名，將自動附加序號": "Split selected pages: choose a base filename; numbers will be appended",
    "無法輸出": "Cannot export",
    "輸出檔案不可覆蓋來源 PDF。": "Output files must not overwrite a source PDF.",
    "覆蓋單頁檔案": "Overwrite single-page files",
    "已有 {p0} 個同名單頁檔案，例如：\n{p1}\n\n是否覆蓋？": "{p0} single-page files already exist, for example:\n{p1}\n\nOverwrite them?",
    "正在拆分單頁 PDF…": "Exporting single-page PDFs…",
    "正在輸出 PDF…": "Exporting PDF…",
    "輸出完成：{p0}": "Export complete: {p0}",
    "已拆分為 {p0} 個單頁 PDF：\n{p1}": "Exported {p0} single-page PDFs:\n{p1}",
    "已輸出 {p0} 頁至：\n{p1}": "Exported {p0} pages to:\n{p1}",
    "輸出完成": "Export complete",
    "輸出失敗": "Export failed",
    "拖曳到另一頁可調整順序": "Drag to another page to change the order",
    "第 {p0} 頁": "Page {p0}",
    "☰ 拖曳排序": "☰ Reorder",
    "載入中…": "Loading…",
    "無法產生預覽": "Preview unavailable",
    "找不到來源 PDF 檔案：{p0}": "Source PDF not found: {p0}",
    "目前不支援密碼保護的 PDF：{p0}": "Password-protected PDFs are not supported: {p0}",
    "選取的頁碼超出來源 PDF 範圍：{p0}": "Selected page numbers are outside the source PDF: {p0}",
    "請至少選取一頁。": "Select at least one page.",
    "部分單頁檔案已存在，請確認覆蓋或更換檔名。": "Some single-page files already exist. Confirm overwrite or choose another filename.",
    "拆分輸出失敗；已完成 {p0} / {p1} 個檔案。\n{p2}": "Split export failed; {p0} / {p1} files completed.\n{p2}",
    "找不到來源 PDF 檔案。": "Source PDF not found.",
    "目前不支援密碼保護的 PDF。": "Password-protected PDFs are not supported.",
    "無法讀取這個 PDF，檔案可能已損壞或格式不受支援。": "Could not read this PDF. It may be damaged or use an unsupported format.",
    "這個 PDF 沒有可用的頁面。": "This PDF has no pages.",
    "無法啟動 PDF 預覽後端。": "Could not start the PDF preview backend.",
    "PDF 預覽後端未正確啟動。": "The PDF preview backend did not start correctly.",
    "PDF 預覽後端驗證失敗。": "PDF preview backend authentication failed.",
    "無法啟動封裝版 PDF 預覽後端。": "Could not start the packaged PDF preview backend.",
    "PDF 預覽後端已停止。": "The PDF preview backend has stopped.",
    "跟隨系統": "Follow system",
    "中文": "Chinese",
    "淺色": "Light",
    "深色": "Dark",
    "介面語言": "Interface language",
    "介面配色": "Color theme",
    "介面語言：{mode}（目前：{language}）\n點擊依序切換：跟隨系統 → 中文 → English": "Interface language: {mode} (current: {language})\nClick to cycle: Follow system → Chinese → English",
    "介面配色：{mode}\n點擊依序切換：跟隨系統 → 淺色 → 深色": "Color theme: {mode}\nClick to cycle: Follow system → Light → Dark",
}


def tr(source: str, **values) -> str:
    return (ENGLISH.get(source, source) if LANGUAGE == "en" else source).format(**values)


def _pattern(template):
    parts = []
    for literal, field, _, _ in Formatter().parse(template):
        parts.append(re.escape(literal))
        if field is not None:
            parts.append(f"(?P<{field}>.*?)")
    return re.compile("".join(parts), re.DOTALL)


_PATTERNS = [(zh, en, _pattern(zh), _pattern(en)) for zh, en in ENGLISH.items()]


def localize_text(text: str) -> str:
    """Retranslate existing text without changing filenames or user-provided values."""
    for zh, en, zh_pattern, en_pattern in _PATTERNS:
        match = zh_pattern.fullmatch(text) or en_pattern.fullmatch(text)
        if match:
            return (en if LANGUAGE == "en" else zh).format(**match.groupdict())
    return text
