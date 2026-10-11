# repdf 實作與維護指南

本文件描述 repdf 目前的程式架構、主要資料流、重要設計決策與修改注意事項。若要新增功能或除錯，建議先閱讀本文件，再從 `src/repdf/app.py` 進入程式。

## 1. 專案概觀

repdf 是 Windows 優先的 Python 桌面程式，功能是：

1. 以可勾選、拖曳排序及關閉的標籤頁開啟多個 PDF。
2. 顯示所有頁面的可捲動預覽。
3. 拖曳縮圖或把手調整頁面排列，手動或依原始頁碼的奇偶選取頁面。
4. 依畫面排列順序將選取頁面輸出成新 PDF。

執行環境由 `uv` 管理，Python 版本需求為 3.11 以上。

```powershell
uv sync
uv run repdf
uv run pytest
```

## 2. 技術組成

| 套件 | 用途 |
| --- | --- |
| PySide6 | 視窗、控制項、主題、執行緒池與 Qt 訊號 |
| pypdf | 驗證來源 PDF、讀取頁數、無損複製選取頁面 |
| pypdfium2 | 在獨立處理程序中將 PDF 頁面渲染為縮圖 |
| Pillow | 將 PDFium bitmap 儲存為 PNG |
| pytest | 核心與整合測試 |
| pytest-qt | Qt GUI 與非同步行為測試 |

## 3. 目錄與模組責任

```text
src/repdf/
├── app.py             主視窗與独立文件元件 DocumentView、標籤、GUI 事件與資料流協調
├── core.py            不依賴 GUI 的選取、驗證與 PDF 輸出邏輯
├── widgets.py         單一頁面預覽卡片 PageCard
├── theme.py           系統深色／淺色模式與控制項樣式
├── workers.py         PDF 載入及輸出的 QRunnable 工作
├── renderer.py        常駐縮圖後端程序與主程序之間的通訊
├── render_worker.py   子程序內的 PDFium 渲染服務
└── assets/            PNG 與 Windows ICO 應用程式圖示

tests/
├── test_core.py       選取規則、PDF 驗證與輸出測試
├── test_gui.py        GUI 狀態、多檔標籤、跨檔輸出與預覽整合測試
└── test_renderer.py   各文件要求合併、優先順序與取消測試
```

## 4. 啟動與元件生命週期

公開入口為 `repdf.entrypoint:main`，一般啟動交由 `repdf.app:main`；封裝版渲染服務與 `--self-test` 由 entrypoint 分派。

啟動順序刻意設計如下：

1. `start_render_backend()` 先啟動常駐 PDF 預覽子程序。
2. 建立 `QApplication`。
3. `configure_application()` 設定 Fusion 樣式、圖示與繁中字型回退。
4. 建立 `ThemeController`，套用目前系統配色並監聽後續變化。
5. 建立 `MainWindow`，把已啟動的預覽後端交給 `RenderService`。

不要把預覽後端移回 GUI 執行緒，也不要直接在多個執行緒中呼叫 PDFium。PDFium 本身不是 thread-safe；目前用單一常駐子程序隔離原生渲染狀態，並確保主視窗不會因預覽工作凍結。

視窗關閉時，`closeEvent()` 會：

- 設定 `_closing`，停止各文件縮放 timer，讓未完成的舊結果失效。
- 結束預覽子程序。
- 清除尚未開始的 Qt 工作並等待進行中的輸出工作結束。
- 清理預覽 PNG 暫存目錄。

## 5. 主視窗與狀態

主畫面在 `MainWindow.__init__()` 中建立，分為三個區域：

- 上方固定工具列：開啟 PDF、輸出選取頁面、固定寬度比例顯示及其右側的比例滑桿。點擊比例回到 100%，完整縮放說明集中於比例 tooltip。放大／縮小 QAction 掛於主視窗，僅提供快捷鍵。檔案操作由 QAction 統一管理啟用狀態與快捷鍵，完整來源路徑顯示於視窗標題列。
- 單數頁／雙數頁三態核取方塊位於工具列的檔案操作按鈕後方；中央為標籤頁與各文件的可捲動頁面網格。
- 下方狀態列：載入、選取及輸出進度。

`MainWindow` 管理共享工具列、`QTabWidget`、固定文件 ID 與輸出工作 ID；`DocumentView` 各自持有來源、頁數、`selected_pages`、`page_order`、`page_cards`、縮放比例、渲染世代與捲動區。切換標籤時同步工具列、標題與奇偶頁三態，不重建文件內容。標籤核取方塊與關閉按鈕綁定文件物件，不以易變的標籤索引保存狀態。

`_active_tasks` 保留 `QRunnable` 的 Python 參考，完成或失敗後才移除。背景載入以文件 ID 回傳；輸出完成以 `_export_id` 回傳，不受目前標籤影響。

## 6. PDF 載入流程

`choose_pdf()` 使用多選對話框，與多檔拖入共用 `load_pdfs()`：

1. 依輸入順序建立載入中的標籤；同一 resolved 路徑已存在時切換到既有標籤。
2. 以 `LoadPdfTask` 在共用 `QThreadPool` 中呼叫 `core.inspect_pdf()`。
3. 成功後由對應 `DocumentView` 建立卡片；首次啟用該標籤才要求預覽，之後保留快取。
4. 失敗時移除該標籤，保留其他成功文件；同批錯誤在全部載入完成後合併呈現。
5. 已關閉文件的回傳結果只完成工作清理，不重新建立標籤。

密碼保護 PDF 是刻意不支援的第一版限制，會拋出 `UnsupportedEncryptedPdfError`。

## 7. 預覽渲染架構

### 7.1 為何使用獨立處理程序

`pypdfium2` 只在 `render_worker.py` 子程序內匯入。主 GUI 不直接載入 PDFium，避免原生函式庫的 thread-safety 與 GUI 字型／繪圖狀態互相影響。

`RenderService` 使用 stdin/stdout 傳送每行一筆 JSON：

請求：

```json
{
  "source": "C:/path/input.pdf",
  "scale": 1.3333333333,
  "output_dir": "C:/Temp/repdf-preview-...",
  "generation": 4
}
```

逐頁結果：

```json
{
  "type": "page",
  "generation": 4,
  "page": 0,
  "path": "C:/Temp/repdf-preview-.../g4-p0.png"
}
```

完成或失敗：

```json
{"type": "done", "generation": 4}
{"type": "error", "generation": 4, "message": "..."}
```

GUI 收到單頁結果後會把 PNG 完整複製成 `QImage`，立即刪除該暫存 PNG，再更新對應卡片。

### 7.2 最新要求優先

後端一次只執行一個渲染要求。`RenderService` 使用依文件 ID 索引的待處理佇列，各文件只保留最新一筆要求；目前標籤優先。`cancel_pending()` 在關閉文件時移除尚未開始的要求。

世代編號由主視窗全域遞增，透過 `_render_documents` 對應到文件 ID，線上 JSON 格式維持不變。結果交給來源文件，與目前標籤或標籤順序無關；比例過期或文件已關閉的頁面結果直接清理暫存圖片。進行中的原生渲染不強制中斷，避免不安全的 PDFium 操作。

### 7.3 縮放定義

100% 以 Windows 標準 96 DPI 顯示 PDF 的 72 DPI 點數：

```text
render_scale = slider_percent / 100 × 96 / 72
```

因此 300pt 寬的頁面在 100% 時約為 400px。每一頁依自己的實際尺寸渲染，橫向頁面不會被強制壓成與直向頁面相同寬度。

滑桿有 250ms 防抖；連續拖動時只會在停止變動後送出渲染要求。若修改比例範圍或 DPI 定義，需同步檢查：

- `DocumentView._preview_scale()`
- `DocumentView._target_preview_width()`
- `render_worker.render_document()`
- `test_pdf_loads_and_renders_page_previews`

## 8. 網格與頁面卡片

`PageCard` 持有：

- 顯示自然頁碼的 `QCheckBox`。
- 顯示縮圖或錯誤狀態的 `QLabel`。
- 零起始 `page_index`。

圖片到達後，卡片會依縮圖實際寬高調整固定尺寸。`DocumentView._reflow_grid()` 以目前最寬卡片和預覽區可用寬度計算欄數；視窗改變大小或新縮圖到達時都會重新排列，但不重新解析 PDF。

`PageGrid` 管理拖曳預覽：開始時固定原始網格位置、暫停 layout 並隱藏來源卡片；`QDrag` 使用含頁碼的卡片縮圖（最大 180×240px）。滑鼠以原始格位的左／右半部決定前／後插入，避免移動中的卡片反覆改變命中位置。其餘卡片使用 180ms OutCubic 位置動畫讓出虛線空位，跨列時依網格順序換列。預覽不修改 `page_order`；放開才透過 `_insert_page()` 提交，取消則恢復原始網格。拖曳結束後重新啟用 layout 並重排，輸出期間禁止開始拖曳。

## 9. 頁面選取規則

內部一律使用零起始索引；畫面一律顯示一開始頁碼。

`core.py` 提供純函式：

- `indices_for_parity()`：取得奇數或偶數自然頁碼所對應的索引。
- `set_parity()`：只增加或移除指定奇偶群組，不改動另一群組。
- `parity_state()`：回傳 `NONE`、`PARTIAL` 或 `ALL`。

奇數頁與偶數頁控制項為三態核取方塊。手動勾選部分群組時顯示部分選取；同時全選奇數與偶數頁等同全選。程式化同步核取狀態時，必須保留 `_syncing_bulk` 或阻擋訊號，避免重入選取邏輯。

## 10. PDF 輸出與檔案安全

`choose_output()` 使用系統另存新檔視窗，預設名稱為 `<來源檔名>_selected.pdf`。輸出按鈕只在至少選一頁且沒有輸出工作時啟用。

`core.export_documents()` 的重要行為（既有 `export_selected_pages()` 保留為單檔包裝）：

1. GUI 依標籤順序取得有勾選的文件；若沒有勾選標籤則只取目前文件。各文件依 `page_order` 過濾 `selected_pages`，組成不可變 `DocumentSelection(source, pages)` 清單。空選頁的文件不提供輸出頁面。
2. 禁止目的地與參與輸出或任何已開啟的來源為同一檔案。
3. 驗證頁碼範圍與來源是否仍存在。
4. 使用 pypdf 直接加入原始頁面，不以縮圖重建 PDF。
5. 複製第一個實際提供頁面的文件 metadata。
6. 先在目的資料夾寫入 `.repdf-*.pdf` 暫存檔。
7. 寫入完成並 `fsync()` 後，以 `os.replace()` 原子替換目的檔。
8. 發生錯誤時刪除暫存檔，不留下半成品。

拖曳排序只移動 `page_order` 的原始頁碼索引，`page_cards` 和 `selected_pages` 仍以原始頁碼識別頁面。單雙數選取完全不受畫面位置影響。

單頁拆分由 `choose_split_output()` 共用另存流程，透過 `ExportPdfTask(split=True)` 呼叫 `core.split_documents()`（`split_selected_pages()` 保留為單檔包裝）。`split_output_paths()` 依輸出總數產生至少兩位補零的連續序號。GUI 在啟動前確認實際單頁檔案的覆蓋，核心再次禁止覆蓋來源。每個來源只讀取一次，各頁保留其所屬來源的原始頁面與 metadata；先在同一目的資料夾的暫存目錄產生所有 PDF，再逐檔原子發布。未授權覆蓋時，發布操作拒絕已存在的檔案。產生失敗不會修改輸出；若發布階段因磁碟錯誤中斷，錯誤訊息會顯示已完成的檔案數，先前發布的檔案會保留。

輸出期間允許切換標籤查看與縮放，但禁止開檔、關閉、標籤勾選／排序與頁面選取／重排。背景輸出使用開始時的不可變快照；全部選頁為空時停用輸出按鈕，不自動回退到其他檔案。拆分序號跨檔連續，沿用至少兩位補零。

## 11. 主題、字型與圖示

工具列提供 `language_action`、`theme_action` 三態按鈕，分別循環 `system → zh → en` 與 `system → light → dark`。`QSettings("repdf", "repdf")` 的 `ui/language`、`ui/theme` 保存選擇，預設均為 `system`，無效值回退為系統模式。首次啟動會將舊版 `QSettings("PDFPick", "PDFPick")` 的有效語言與配色選擇複製到尚未設定的新欄位，不覆蓋 repdf 已有設定，也不刪除舊設定。

`preferences.LanguageController` 優先使用 `QLocale.system().uiLanguages()` 的第一個顯示語言，沒有顯示語言時才回退至 locale 語言；中文使用繁體中文，其餘使用英文。主視窗收到 `LocaleChange` 時僅在系統模式重新判斷。`strings.py` 集中翻譯表與 `tr()`，由 GUI、核心和背景錯誤共用；`localize_text()` 更新既有介面文字並保留格式化參數。切換時更新文字與提示，不重建文件或重新渲染頁面。

檔案對話框使用 `DontUseNativeDialog`，搭配 Qt `qtbase_zh_TW.qm` 與標準按鈕翻譯。封裝設定透過 `QLibraryInfo.TranslationsPath` 取得各平台的 Qt 翻譯資源路徑，將 qm 放入 `repdf/assets`；來源執行同樣讀取 Qt 的 translations 路徑。未翻譯文字回退原文。`packaging_smoke.py` 驗證 qm 存在與英文翻譯，GUI 測試以獨立設定檔隔離使用者偏好。

`ThemeController` 在 `system` 模式讀取 `QGuiApplication.styleHints().colorScheme()`，並監聽 `colorSchemeChanged`；`light`、`dark` 則優先使用手動設定。控制器由主視窗持有。每次套用主題時同時更新：

- Qt palette。
- 頁面卡片與預覽區邊框。
- 按鈕基本尺寸。
- 滑桿軌道、已填區段與把手顏色。
- 工具列、核取方塊、捲軸與對話框按鈕的扁平樣式。`icons.py` 繪製工具列線條圖示；主視窗在 palette 改變時重建圖示，維持深淺色及停用狀態的可讀性。

`configure_application()` 依序嘗試：

1. Microsoft JhengHei UI
2. Microsoft JhengHei
3. Noto Sans TC
4. Arial

圖示位於 `src/repdf/assets/repdf.png` 與 `repdf.ico`。目前程式使用 PNG 建立 `QIcon`；ICO 提供未來 Windows EXE 打包使用，內含 16、24、32、48、64、128、256px 尺寸。

## 12. 測試覆蓋範圍

目前測試涵蓋：

- 奇偶頁選取、清除與三態判定。
- 預設輸出檔名。
- 集合選取依來源順序輸出；有序清單依拖曳順序輸出。
- 拖曳重排後，畫面順序、原始頁碼奇偶選取與實際輸出一致。
- 輸出後頁面尺寸保持不變。
- 空選取與覆蓋來源檔的拒絕行為。
- 損壞與密碼保護 PDF。
- GUI 初始控制項與圖示載入。
- 手動頁面選取與奇偶頁狀態同步。
- 縮放防抖。
- 從 PDF 載入到背景渲染縮圖的整合流程。

測試使用 `QT_QPA_PLATFORM=offscreen`。Qt 的離屏外掛可能和原生 Windows 視窗有細微繪圖差異，因此涉及字型、圖示、主題或版面外觀的修改，仍應額外用原生 Windows 視窗檢查。

## 13. 常見修改入口

| 修改需求 | 主要入口 | 注意事項 |
| --- | --- | --- |
| 調整主畫面排列 | `MainWindow.__init__()` | 保持上、中、下三區結構 |
| 調整縮放範圍或 DPI | `app.py` 的 slider 與 scale 方法 | 同步更新測試與 README |
| 改縮圖格式或品質 | `render_worker.render_document()` | 主程序目前假設收到可由 `QImage` 讀取的路徑 |
| 改背景任務排程 | `renderer.RenderService` | 保留 generation 淘汰機制 |
| 新增選取方式 | `core.py` 純函式及 `_selection_updated()` | 以零起始索引為內部標準 |
| 改輸出順序 | `DocumentView.page_order`、`_move_page()`、`core.export_selected_pages()` | 保持原始頁碼索引與畫面位置分離 |
| 支援加密 PDF | `core.inspect_pdf()` 與輸出流程 | 需設計密碼輸入及密碼生命週期 |
| 更換圖示 | `assets/` 與 `load_app_icon()` | PNG 與 ICO 應同步更新 |
| 調整深淺色配色 | `ThemeController.apply()` | 必須同時確認兩種系統模式 |

## 14. 已知限制與擴充方向

- 不支援跨標籤拖移頁面或重啟後還原工作階段。
- 不支援密碼保護 PDF。
- 不支援旋轉、裁切或多 PDF 合併。
- 所有已渲染縮圖都保留在記憶體；極大量頁數或 200% 比例可能有較高記憶體用量。若要改善，優先考慮可視區域延遲渲染與縮圖快取淘汰。
- 後端忙碌時不會中斷目前 PDF，而是等待完成後處理最新要求；大型 PDF 的快速縮放可進一步加入可取消的工作協定。
- GitHub Actions 可產出 Windows 單一 EXE 與 macOS App／DMG；目前未設定開發者簽章與 macOS 公證。

## 15. 桌面套件打包

- packaging/repdf.spec：Windows 使用 onefile windowed EXE；macOS 使用 onedir App bundle，保留原生函式庫的符號連結後封裝為 DMG。
- scripts/build_desktop.py：執行 PyInstaller、封裝後功能檢查、DMG 建立與 SHA256 校驗檔產生。
- .github/workflows/build-desktop.yml：兩個 GitHub 雲端原生 runner 建置 Windows x86_64 與 macOS arm64；Release 成功建置後才附加產物。
- entrypoint.py：在載入 GUI 前辨識背景後端與封裝自我檢查模式，避免子程序再次開啟 GUI。
- renderer.py：來源碼模式沿用 stdin/stdout；凍結模式以 loopback TCP、一次性隨機握手 token 與 UTF-8 串流通訊，因為 Windows windowed bootloader 沒有標準輸入輸出。
- packaging_smoke.py：在封裝執行檔中實際渲染兩頁 PDF、載入 Qt 圖示並驗證指定順序的 PDF 輸出。
- 版本資訊讀取已安裝的 repdf distribution metadata；PyInstaller 同時收集該 metadata，避免視窗與套件版本不同步。

PyPI 發布需先為 `codemee/repdf` 配置 repdf 專案的 Trusted Publisher，並將儲存庫變數 `PYPI_PUBLISH_ENABLED` 設為 `true`；未啟用時只使用 GitHub Release 發布。
