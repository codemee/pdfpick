# RePDF — Rearrange PDF

RePDF 是 **Rearrange PDF** 的意思，命令名稱與 Python 套件名稱為 `repdf`。這是使用 PySide6 製作的 Windows 桌面工具，可用標籤頁開啟多個 PDF、勾選指定頁面，並依標籤與頁面排列順序重組或拆分輸出。預覽縮圖不會影響輸出品質。

## 安裝與啟動

### 1. 下載發布的執行檔／App（建議）

從 [GitHub Releases](https://github.com/codemee/repdf/releases/latest) 下載適合平台的檔案，不需要安裝 Python 或 uv：

- **Windows x86_64**：下載 `repdf-<版本>-windows-x86_64.exe`，直接執行。
- **macOS Apple Silicon（arm64）**：下載 `repdf-<版本>-macos-arm64.dmg`，開啟後將 `RePDF.app` 拖入 Applications，再從 Applications 啟動。

既有 `v0.0.7` 及較早的 Release 仍使用 `PDFPick` 檔名與 `PDFPick.app`，`v0.0.8` 的 macOS App 名稱為 `repdf.app`；後續 App 名稱統一為 `RePDF.app`，命令與發布檔案前綴仍為 `repdf`。

Release 同時提供 SHA256 校驗檔。簽章與打包資訊見下方「Windows 執行檔與 macOS App／DMG」。

### 2. 使用 uv tool 安裝

已有 [uv](https://docs.astral.sh/uv/) 時，可從 PyPI 安裝到獨立工具環境：

```powershell
uv tool install repdf
repdf
```

需要 Python 3.11 以上版本；uv 可在需要時下載適用的 Python。也可使用 Release 的 `repdf` wheel 下載網址安裝。若終端機找不到 `repdf`，執行 `uv tool update-shell` 後重新開啟終端機。既有舊版 wheel 仍安裝為 `pdfpick` 指令。

### 3. 從原始碼使用 uv run

適合開發或修改程式。下載原始碼，或 clone 本儲存庫後，進入專案目錄執行：

```powershell
uv sync
uv run repdf
```

## 操作方式

工具列按鈕的圖示與用途如下；將游標停在按鈕上也可查看 tooltip。

| 工具列圖示／控制元件 | 功能 | 操作說明 | 快捷鍵 |
| --- | --- | --- | --- |
| <img src="docs/images/toolbar-open.png" width="24" alt="開啟 PDF 圖示"> | 開啟 PDF | 一次選取多個 PDF，也可從檔案總管拖入。 | Ctrl+O |
| <img src="docs/images/toolbar-export.png" width="24" alt="重組輸出圖示"> | 重組輸出 | 將選取頁面依目前順序合併為一個新 PDF，指定檔名與儲存位置。 | Ctrl+S／Ctrl+Shift+S |
| <img src="docs/images/toolbar-split.png" width="24" alt="拆分輸出圖示"> | 拆分輸出 | 將選取頁面依目前順序逐頁存成獨立 PDF，指定基本檔名與儲存位置。 | — |
| <img src="docs/images/toolbar-odd.png" height="22" alt="單數頁核取方塊"> | 單數頁 | 選取或取消目前標籤的原始單數頁；部分選取時顯示三態標記。 | — |
| <img src="docs/images/toolbar-even.png" height="22" alt="雙數頁核取方塊"> | 雙數頁 | 選取或取消目前標籤的原始雙數頁；部分選取時顯示三態標記。 | — |
| <img src="docs/images/toolbar-zoom.png" width="160" alt="顯示比例與縮放滑桿"> | 顯示比例 | 滑桿調整 25%–200%；點擊比例回到 100%。鍵盤縮放每次調整 25 個百分點，完整說明在比例的 tooltip。 | 放大：Ctrl++／Ctrl+=；縮小：Ctrl+-；100%：Ctrl+0 |
| <img src="docs/images/toolbar-fit.png" width="24" alt="Fit 圖示"> | Fit | 將目前單頁等比例縮放至預覽區；調整視窗大小時自動適應。拖動滑桿或使用縮放快捷鍵會回到手動比例。 | — |
| <img src="docs/images/toolbar-fullscreen.png" width="24" alt="全螢幕單頁圖示"> | 全螢幕單頁 | 每次顯示一頁，依螢幕寬度或高度等比例填滿；可用頁面上方的核取方塊選頁。 | F11 開啟／返回；Esc 返回 |
| <img src="docs/images/toolbar-fullscreen-spread.png" width="24" alt="全螢幕對頁圖示"> | 全螢幕對頁 | 依目前順序兩頁並排：第 1、2 頁一組，第 3、4 頁一組，以此類推；每頁可獨立勾選。 | Esc／F11 返回 |
| <img src="docs/images/toolbar-fullscreen-cover.png" width="24" alt="全螢幕封面加對頁圖示"> | 全螢幕封面＋對頁 | 目前順序的第一頁作為封面單獨顯示；第 2、3 頁一組，第 4、5 頁一組，以此類推；每頁可獨立勾選。 | Esc／F11 返回 |
| <img src="docs/images/toolbar-language-system.png" width="24" alt="跟隨系統語言"> <img src="docs/images/toolbar-language-zh.png" width="24" alt="繁體中文"> <img src="docs/images/toolbar-language-en.png" width="24" alt="English"> | 介面語言 | 點擊依序切換「跟隨系統 → 繁體中文 → English」，選擇會記住。 | — |
| <img src="docs/images/toolbar-theme-system.png" width="24" alt="跟隨系統配色：太陽與月亮"> <img src="docs/images/toolbar-theme-light.png" width="24" alt="淺色：太陽"> <img src="docs/images/toolbar-theme-dark.png" width="24" alt="深色：月亮"> | 介面配色 | 點擊依序切換「跟隨系統 → 淺色 → 深色」，選擇會記住。 | — |

各檔案以主檔名顯示在標籤頁，完整路徑顯示於標籤 tooltip；視窗標題列只顯示 `RePDF` 與版本編號。同一路徑再次開啟會切換到既有標籤。預覽頁面水平置中，Fit 使用單欄顯示。各檔案獨立保留比例、捲動位置、選頁與頁面排序；100% 對應 Windows 的 96 DPI 顯示尺度。

Fit 與全螢幕優先使用最近點擊且仍可見的頁面；未指定時使用預覽區中央附近的頁面。Fit 的適應比例可超出滑桿的手動範圍，實際比例仍顯示於工具列。

方向鍵及 Page Up／Page Down 固定操作預覽區，即使縮放滑桿有焦點也不會改變比例：一般預覽時方向鍵捲動、Page Up／Page Down 捲動一個畫面；Fit 時從目前可見頁面依順序切換上一頁／下一頁，第一頁與最後一頁不會越界，反向按一次即可切頁。全螢幕時左／上／Page Up 顯示上一頁或上一組，右／下／Page Down 顯示下一頁或下一組。對頁以同一比例完整顯示兩頁，最後剩一頁時單獨顯示。

全螢幕的核取方塊會同步主視窗的選頁，返回後即可重組或拆分，原有縮放比例保留。核取方塊取得焦點後也可用空白鍵勾選。

點選各頁左上角的核取方塊可個別選頁。拖曳頁面縮圖或「拖曳排序」把手時，縮圖會跟隨游標，其他頁面以動畫移開並顯示插入空位。移到頁面左半部可插入其前方，右半部可插入其後方；放開確認排序，按 Esc 取消。

拆分時，例如指定 `report.pdf`，會輸出 `report_01.pdf`、`report_02.pdf`。序號從 1 開始，至少兩位，依本次輸出總數補零對齊（100 頁使用 `001`–`100`），與原始頁碼無關。已存在的單頁檔案會先詢問是否覆蓋。

標籤左側核取方塊預設不勾選。有勾選標籤時，只輸出勾選檔案的已選頁面；沒有勾選任何標籤時，只輸出目前標籤的已選頁面。勾選檔案沒有選頁時不提供輸出頁面，不會自動改選目前檔案。拖曳標籤可調整檔案順序，輸出先依標籤順序，再依各檔內的頁面排序；拆分序號跨檔連續。按標籤右側的 × 可關閉檔案。

密碼保護的 PDF 暫不支援。輸出頁面依畫面排列順序；未勾選的頁面不會輸出。

## 語言與配色

工具列右側提供兩個三態按鈕，首次使用皆預設跟隨系統，點擊即可立即切換：

- 介面語言：跟隨系統 → 繁體中文 → English → 跟隨系統。系統顯示語言為中文時使用繁體中文，其他語言使用 English；tooltip 顯示目前模式與實際語言。
- 介面配色：跟隨系統 → 淺色 → 深色 → 跟隨系統。手動指定配色後不受系統配色變化影響，回到系統模式則即時跟隨。

選擇會記住，重新啟動仍保留。切換語言會更新既有頁面標籤、工具列、tooltip、狀態與對話框，不改動檔名、選頁、頁序或比例。檔案對話框採用 Qt 介面，讓按鈕與欄位也能跟隨指定的中英文語言。

## 測試

```powershell
uv run pytest
```

## 開發與維護

目前架構、背景預覽協定、縮放定義、輸出安全機制與修改入口整理於 [實作與維護指南](docs/IMPLEMENTATION.md)。

## Windows 執行檔與 macOS App／DMG

GitHub Actions 的「Build desktop apps」會在 main 更新、PR 或 Release 發佈時打包，也可在 Actions 頁面以 Run workflow 手動執行並指定分支或標籤。Release 的標籤必須包含打包設定檔。

產物包含 Windows x86_64 單一 EXE、macOS Apple Silicon（arm64）DMG，以及 SHA256 校驗檔。手動執行與一般提交的產物可從 Actions 的 Artifacts 下載；Release 發佈時會自動附加到該 Release。DMG 中可將 RePDF.app 拖入 Applications，不需要另外安裝 Python。

目前未設定 Windows 程式碼簽章或 macOS Developer ID 簽章／公證，因此下載後可能出現系統的安全提示；這些套件並非已公證的 macOS 發行版。

打包全程在 GitHub 雲端環境執行。流程會先驗證 Qt、圖示、背景 PDF 渲染與重排輸出；macOS 使用系統內建的 ditto 與 hdiutil 建立並驗證 DMG。Actions 產物保留 30 天。
