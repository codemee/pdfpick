# PDFPick 實作與維護指南

本文件描述 PDFPick 目前的程式架構、主要資料流、重要設計決策與修改注意事項。若要新增功能或除錯，建議先閱讀本文件，再從 `src/pdfpick/app.py` 進入程式。

## 1. 專案概觀

PDFPick 是 Windows 優先的 Python 桌面程式，功能是：

1. 開啟單一 PDF。
2. 顯示所有頁面的可捲動預覽。
3. 拖曳縮圖或把手調整頁面排列，手動或依原始頁碼的奇偶選取頁面。
4. 依畫面排列順序將選取頁面輸出成新 PDF。

執行環境由 `uv` 管理，Python 版本需求為 3.11 以上。

```powershell
uv sync
uv run pdfpick
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
src/pdfpick/
├── app.py             主視窗、狀態管理、GUI 事件與資料流協調
├── core.py            不依賴 GUI 的選取、驗證與 PDF 輸出邏輯
├── widgets.py         單一頁面預覽卡片 PageCard
├── theme.py           系統深色／淺色模式與控制項樣式
├── workers.py         PDF 載入及輸出的 QRunnable 工作
├── renderer.py        常駐縮圖後端程序與主程序之間的通訊
├── render_worker.py   子程序內的 PDFium 渲染服務
└── assets/            PNG 與 Windows ICO 應用程式圖示

tests/
├── test_core.py       選取規則、PDF 驗證與輸出測試
└── test_gui.py        GUI 狀態、縮放防抖與預覽整合測試
```

## 4. 啟動與元件生命週期

公開入口為 `pdfpick.app:main`。

啟動順序刻意設計如下：

1. `start_render_backend()` 先啟動常駐 PDF 預覽子程序。
2. 建立 `QApplication`。
3. `configure_application()` 設定 Fusion 樣式、圖示與繁中字型回退。
4. 建立 `ThemeController`，套用目前系統配色並監聽後續變化。
5. 建立 `MainWindow`，把已啟動的預覽後端交給 `RenderService`。

不要把預覽後端移回 GUI 執行緒，也不要直接在多個執行緒中呼叫 PDFium。PDFium 本身不是 thread-safe；目前用單一常駐子程序隔離原生渲染狀態，並確保主視窗不會因預覽工作凍結。

視窗關閉時，`closeEvent()` 會：

- 增加 `session_id`，讓未完成的舊結果失效。
- 結束預覽子程序。
- 清除尚未開始的 Qt 工作。
- 清理預覽 PNG 暫存目錄。

## 5. 主視窗與狀態

主畫面在 `MainWindow._build_ui()` 中建立，分為三個區域：

- 上方固定工具列：開啟 PDF、輸出選取頁面、固定寬度比例顯示及其右側的比例滑桿。點擊比例回到 100%，完整縮放說明集中於比例 tooltip。放大／縮小 QAction 掛於主視窗，僅提供快捷鍵。檔案操作由 QAction 統一管理啟用狀態與快捷鍵，完整來源路徑顯示於視窗標題列。
- 中列：奇偶頁控制列及可捲動、自動換欄的頁面網格。
- 下方狀態列：載入、選取及輸出進度。

主要狀態欄位：

| 欄位 | 意義 |
| --- | --- |
| `source_path` | 目前來源 PDF；未載入時為 `None` |
| `page_count` | 來源頁數 |
| `selected_pages` | 已選頁面的零起始索引集合 |
| `page_cards` | 依原始頁碼索引存放的 `PageCard`；背景預覽以此索引更新卡片 |
| `page_order` | 畫面與輸出的原始頁碼索引順序；拖曳時只改動此清單 |
| `session_id` | 每次重新載入檔案時遞增，用來淘汰舊載入／輸出結果 |
| `render_generation` | 每次重新渲染時遞增，用來淘汰舊比例的縮圖 |
| `_render_pending` | 目前世代尚未收到的縮圖數量 |
| `_export_running` | 控制輸出期間按鈕狀態 |

`_active_tasks` 必須保留 `QRunnable` 的 Python 參考；工作完成或失敗後才移除，避免 Qt 訊號物件過早被回收。

## 6. PDF 載入流程

`choose_pdf()` 顯示檔案選擇視窗，選到檔案後呼叫 `load_pdf()`：

1. 遞增 `session_id` 並清除舊文件狀態。
2. 以 `LoadPdfTask` 在 `QThreadPool` 中呼叫 `core.inspect_pdf()`。
3. `inspect_pdf()` 確認檔案存在、可解析、至少一頁且未加密。
4. 成功後建立每頁的 `PageCard`，啟用奇偶頁控制並要求背景渲染。
5. 所有回傳結果都先比對 `session_id`；不屬於目前文件的結果直接忽略。

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
  "output_dir": "C:/Temp/pdfpick-preview-...",
  "generation": 4
}
```

逐頁結果：

```json
{
  "type": "page",
  "generation": 4,
  "page": 0,
  "path": "C:/Temp/pdfpick-preview-.../g4-p0.png"
}
```

完成或失敗：

```json
{"type": "done", "generation": 4}
{"type": "error", "generation": 4, "message": "..."}
```

GUI 收到單頁結果後會把 PNG 完整複製成 `QImage`，立即刪除該暫存 PNG，再更新對應卡片。

### 7.2 最新要求優先

後端一次只執行一個渲染要求。若使用者在渲染期間多次拖動滑桿，`RenderService` 只保留最新一筆待處理要求，不累積所有中間比例。

正在執行的舊要求不會強制中斷；它的結果會因 `generation` 不符而被 GUI 忽略。舊要求完成後，後端才處理最新要求。

### 7.3 縮放定義

100% 以 Windows 標準 96 DPI 顯示 PDF 的 72 DPI 點數：

```text
render_scale = slider_percent / 100 × 96 / 72
```

因此 300pt 寬的頁面在 100% 時約為 400px。每一頁依自己的實際尺寸渲染，橫向頁面不會被強制壓成與直向頁面相同寬度。

滑桿有 250ms 防抖；連續拖動時只會在停止變動後送出渲染要求。若修改比例範圍或 DPI 定義，需同步檢查：

- `MainWindow._preview_scale()`
- `MainWindow._target_preview_width()`
- `render_worker.render_document()`
- `test_pdf_loads_and_renders_page_previews`

## 8. 網格與頁面卡片

`PageCard` 持有：

- 顯示自然頁碼的 `QCheckBox`。
- 顯示縮圖或錯誤狀態的 `QLabel`。
- 零起始 `page_index`。

圖片到達後，卡片會依縮圖實際寬高調整固定尺寸。`MainWindow._reflow_grid()` 以目前最寬卡片和預覽區可用寬度計算欄數；視窗改變大小或新縮圖到達時都會重新排列，但不重新解析 PDF。

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

`core.export_selected_pages()` 的重要行為：

1. GUI 依 `page_order` 過濾 `selected_pages` 並傳入有序索引；核心保留清單順序，集合輸入仍依來源順序排序。
2. 禁止目的地與來源為同一檔案。
3. 驗證頁碼範圍與來源是否仍存在。
4. 使用 pypdf 直接加入原始頁面，不以縮圖重建 PDF。
5. 複製可用的文件 metadata。
6. 先在目的資料夾寫入 `.pdfpick-*.pdf` 暫存檔。
7. 寫入完成並 `fsync()` 後，以 `os.replace()` 原子替換目的檔。
8. 發生錯誤時刪除暫存檔，不留下半成品。

拖曳排序只移動 `page_order` 的原始頁碼索引，`page_cards` 和 `selected_pages` 仍以原始頁碼識別頁面。單雙數選取完全不受畫面位置影響。

單頁拆分由 `choose_split_output()` 共用另存流程，透過 `ExportPdfTask(split=True)` 呼叫 `core.split_selected_pages()`。`split_output_paths()` 依輸出總數產生至少兩位補零的連續序號。GUI 在啟動前確認實際單頁檔案的覆蓋，核心再次禁止覆蓋來源。來源只讀取一次，各頁保留原始頁面與 metadata；先在同一目的資料夾的暫存目錄產生所有 PDF，再逐檔原子發布。未授權覆蓋時，發布操作拒絕已存在的檔案。產生失敗不會修改輸出；若發布階段因磁碟錯誤中斷，錯誤訊息會顯示已完成的檔案數，先前發布的檔案會保留。

## 11. 主題、字型與圖示

`ThemeController` 讀取 `QGuiApplication.styleHints().colorScheme()`，並監聽 `colorSchemeChanged`。每次套用主題時同時更新：

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

圖示位於 `src/pdfpick/assets/pdfpick.png` 與 `pdfpick.ico`。目前程式使用 PNG 建立 `QIcon`；ICO 提供未來 Windows EXE 打包使用，內含 16、24、32、48、64、128、256px 尺寸。

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
| 調整主畫面排列 | `MainWindow._build_ui()` | 保持上、中、下三區結構 |
| 調整縮放範圍或 DPI | `app.py` 的 slider 與 scale 方法 | 同步更新測試與 README |
| 改縮圖格式或品質 | `render_worker.render_document()` | 主程序目前假設收到可由 `QImage` 讀取的路徑 |
| 改背景任務排程 | `renderer.RenderService` | 保留 generation 淘汰機制 |
| 新增選取方式 | `core.py` 純函式及 `_selection_updated()` | 以零起始索引為內部標準 |
| 改輸出順序 | `MainWindow.page_order`、`_move_page()`、`core.export_selected_pages()` | 保持原始頁碼索引與畫面位置分離 |
| 支援加密 PDF | `core.inspect_pdf()` 與輸出流程 | 需設計密碼輸入及密碼生命週期 |
| 更換圖示 | `assets/` 與 `load_app_icon()` | PNG 與 ICO 應同步更新 |
| 調整深淺色配色 | `ThemeController.apply()` | 必須同時確認兩種系統模式 |

## 14. 已知限制與擴充方向

- 一次只能載入一個來源 PDF。
- 不支援密碼保護 PDF。
- 不支援旋轉、裁切或多 PDF 合併。
- 所有已渲染縮圖都保留在記憶體；極大量頁數或 200% 比例可能有較高記憶體用量。若要改善，優先考慮可視區域延遲渲染與縮圖快取淘汰。
- 後端忙碌時不會中斷目前 PDF，而是等待完成後處理最新要求；大型 PDF 的快速縮放可進一步加入可取消的工作協定。
- 目前沒有安裝程式或單檔 EXE；`pdfpick.ico` 已準備給後續 PyInstaller 或 Nuitka 打包流程。
