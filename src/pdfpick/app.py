from __future__ import annotations

import sys
import tempfile
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThreadPool, QTimer, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QAction,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QToolBar,
    QTabWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pdfpick.core import (
    SelectionState,
    default_output_path,
    parity_state,
    set_parity,
    split_output_paths,
    DocumentSelection,
)
from pdfpick import __version__
from pdfpick.icons import toolbar_icon
from pdfpick.theme import ThemeController
from pdfpick.renderer import RenderService, start_render_backend
from pdfpick.widgets import PageCard, PageGrid
from pdfpick.workers import ExportPdfTask, LoadPdfTask


class DocumentView(QWidget):
    REFERENCE_PAGE_WIDTH_POINTS = 595
    SCREEN_DPI = 96
    PDF_DPI = 72

    def __init__(self, owner, document_id: int, path: Path) -> None:
        super().__init__()
        self.owner = owner
        self.document_id = document_id
        self.source_path = path.resolve()
        self.page_count = 0
        self.selected_pages = set()
        self.page_order = []
        self.page_cards = []
        self.zoom = 100
        self.ready = False
        self.render_generation = -1
        self._render_received = set()
        self._render_pending = 0
        self._render_done_generation = -1
        self.include_checkbox = QCheckBox()
        self.include_checkbox.setToolTip("勾選此檔案以加入重組或拆分；未勾選任何標籤時僅輸出目前檔案")
        self.include_checkbox.setEnabled(False)
        self.include_checkbox.toggled.connect(owner._sync_controls)
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setToolTip("關閉此檔案")
        self.close_button.setFixedSize(22, 22)
        self.close_button.clicked.connect(lambda: owner.close_tab(owner.tabs.indexOf(self)))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.viewport().installEventFilter(self)
        self.grid_host = PageGrid()
        self.grid_host.insertion_requested.connect(self._insert_page)
        self.grid_host.drag_finished.connect(self._reflow_grid)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(12, 12, 12, 12)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty_label = QLabel("正在讀取 PDF…")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(self.empty_label, 0, 0)
        self.scroll_area.setWidget(self.grid_host)
        root.addWidget(self.scroll_area)
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(250)
        self.render_timer.timeout.connect(self._queue_all_renders)

    def loaded(self, page_count: int) -> None:
        self.page_count = page_count
        self.ready = True
        self.empty_label.hide()
        self.grid.removeWidget(self.empty_label)
        self._create_page_cards()
        for card in self.page_cards:
            card.checkbox.setEnabled(not self.owner._export_running)
        self.include_checkbox.setEnabled(not self.owner._export_running)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow_grid)
        return super().eventFilter(watched, event)

    def show_status(self, message: str) -> None:
        if self.owner.current_document() is self and not self.owner._export_running:
            self.owner.statusBar().showMessage(message)

    def _create_page_cards(self) -> None:
        self.page_order = list(range(self.page_count))
        width = self._target_preview_width()
        for page_index in range(self.page_count):
            card = PageCard(page_index, width)
            card.selection_changed.connect(self._page_selection_changed)
            card.reorder_requested.connect(self._move_page)
            self.page_cards.append(card)
        self._reflow_grid()

    def _target_preview_width(self) -> int:
        return max(
            55,
            round(self.REFERENCE_PAGE_WIDTH_POINTS * self._preview_scale()),
        )

    def _preview_scale(self) -> float:
        return self.zoom / 100 * self.SCREEN_DPI / self.PDF_DPI

    def _reflow_grid(self) -> None:
        if self.grid_host.drag_source is not None:
            return
        if not self.page_cards:
            return
        while self.grid.count():
            self.grid.takeAt(0)
        card_width = max(card.width() for card in self.page_cards)
        available = max(1, self.scroll_area.viewport().width() - 24)
        columns = max(1, (available + self.grid.spacing()) // (card_width + self.grid.spacing()))
        for position, page_index in enumerate(self.page_order):
            card = self.page_cards[page_index]
            self.grid.addWidget(card, position // columns, position % columns)
        self.grid.activate()

    @Slot(int, int)
    def _insert_page(self, source_index: int, insertion: int) -> None:
        if self.owner._export_running or source_index not in self.page_order:
            return
        self.page_order.remove(source_index)
        self.page_order.insert(insertion, source_index)
        self._reflow_grid()
        self.show_status(
            f"已調整第 {source_index + 1} 頁的預覽與輸出順序"
        )

    @Slot(int, int)
    def _move_page(self, source_index: int, target_index: int) -> None:
        if self.owner._export_running or source_index == target_index:
            return
        if source_index not in self.page_order or target_index not in self.page_order:
            return
        source_position = self.page_order.index(source_index)
        target_position = self.page_order.index(target_index)
        self.page_order.pop(source_position)
        insertion = self.page_order.index(target_index)
        if source_position < target_position:
            insertion += 1
        self.page_order.insert(insertion, source_index)
        self._reflow_grid()
        self.show_status(
            f"已調整第 {source_index + 1} 頁的預覽與輸出順序"
        )

    @Slot(int, bool)
    def _page_selection_changed(self, page_index: int, selected: bool) -> None:
        if selected:
            self.selected_pages.add(page_index)
        else:
            self.selected_pages.discard(page_index)
        self._selection_updated()

    def _toggle_parity(self, odd: bool, checked: bool) -> None:
        if self.owner._syncing_bulk:
            return
        self.selected_pages = set_parity(
            self.selected_pages, self.page_count, odd, checked
        )
        for card in self.page_cards:
            card.set_selected(card.page_index in self.selected_pages)
        self._selection_updated()

    def _selection_updated(self) -> None:
        self.owner._sync_controls()

    def set_zoom(self, value: int) -> None:
        if self.zoom == value:
            return
        self.zoom = value
        if self.page_cards:
            self.render_timer.start()

    @Slot()
    def _queue_all_renders(self) -> None:
        if not self.ready or self.owner._closing:
            return
        self.owner._next_generation += 1
        for generation, document_id in list(self.owner._render_documents.items()):
            if document_id == self.document_id:
                self.owner._render_documents.pop(generation)
        self.render_generation = self.owner._next_generation
        self.owner._render_documents[self.render_generation] = self.document_id
        generation = self.render_generation
        self.render_timer.stop()
        self._render_pending = self.page_count
        self._render_done_generation = -1
        self._render_received.clear()
        width = self._target_preview_width()
        for card in self.page_cards:
            card.set_target_width(width)
        self._reflow_grid()
        self.show_status("正在產生頁面預覽…")
        self._reset_render_state()
        self.owner.render_service.request(
            self.source_path,
            self._preview_scale(),
            Path(self.owner.preview_temp.name),
            generation,
            document_id=self.document_id,
        )

    @Slot(object)
    def _handle_render_message(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        try:
            generation = int(payload.get("generation", -1))
        except (TypeError, ValueError):
            return
        if generation != self.render_generation:
            return
        if kind == "page":
            self._accept_render_page(payload)
        elif kind == "done":
            self._render_done_generation = generation
            self.show_status(
                f"已載入 {self.page_count} 頁；已選取 {len(self.selected_pages)} 頁"
            )
        elif kind == "error":
            for page_index, card in enumerate(self.page_cards):
                if page_index not in self._render_received:
                    card.set_render_error()
            self.show_status("部分頁面無法產生預覽")
            QMessageBox.warning(
                self.owner, "預覽失敗", f"無法完成頁面預覽：\n{payload.get('message', '')}"
            )

    def _accept_render_page(self, payload: dict[str, object]) -> None:
        try:
            page_index = int(payload["page"])
            image_path = Path(payload["path"])
        except (KeyError, TypeError, ValueError):
            return
        image = QImage(str(image_path)).copy()
        if 0 <= page_index < len(self.page_cards) and not image.isNull():
            self.page_cards[page_index].set_image(image)
            self._reflow_grid()
        elif 0 <= page_index < len(self.page_cards):
            self.page_cards[page_index].set_render_error()
        image_path.unlink(missing_ok=True)
        if page_index not in self._render_received:
            self._render_received.add(page_index)
            self._render_pending -= 1
        if self._render_pending == 0:
            self.show_status(
                f"已載入 {self.page_count} 頁；已選取 {len(self.selected_pages)} 頁"
            )

    def _reset_render_state(self) -> None:
        self._render_received.clear()



class MainWindow(QMainWindow):
    def __init__(self, render_backend=None) -> None:
        super().__init__()
        self._update_window_title()
        self.setWindowIcon(load_app_icon())
        self.resize(1040, 760)
        self.setMinimumSize(720, 520)
        self.setAcceptDrops(True)
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(4)
        self.preview_temp = tempfile.TemporaryDirectory(prefix="pdfpick-preview-")
        self.render_service = RenderService(render_backend if render_backend is not None else start_render_backend(), self)
        self.render_service.message.connect(self._handle_render_message, Qt.ConnectionType.QueuedConnection)
        self.documents = {}
        self._next_document_id = 0
        self._next_generation = 0
        self._render_documents = {}
        self._active_tasks = set()
        self._load_batches = {}
        self._document_batches = {}
        self._next_batch = 0
        self._export_running = False
        self._export_id = 0
        self._syncing_bulk = False
        self._closing = False
        self._build_toolbar()
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 12)
        self.empty_label = QLabel("請先開啟 PDF 檔案，或將多個 PDF 拖曳到視窗")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabBar().tabMoved.connect(self._sync_controls)
        self.tabs.hide()
        root.addWidget(self.tabs)
        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("就緒")

    def _build_toolbar(self) -> None:
        self.toolbar = QToolBar("檔案與顯示", self)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(self.toolbar)

        self.open_action = QAction("開啟 PDF", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.setToolTip("開啟 PDF（Ctrl+O）")
        self.open_action.triggered.connect(self.choose_pdf)
        self.toolbar.addAction(self.open_action)
        self.export_action = QAction("輸出選取頁面", self)
        self.export_action.setShortcuts([QKeySequence("Ctrl+S"), QKeySequence("Ctrl+Shift+S")])
        self.export_action.setToolTip("輸出選取頁面為新 PDF（Ctrl+S / Ctrl+Shift+S）")
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self.choose_output)
        self.toolbar.addAction(self.export_action)
        self.split_action = QAction("拆分選取頁面", self)
        self.split_action.setToolTip("拆分選取頁面：依目前順序存成單頁 PDF，檔名附加補零序號")
        self.split_action.setEnabled(False)
        self.split_action.triggered.connect(self.choose_split_output)
        self.toolbar.addAction(self.split_action)
        self.toolbar.addSeparator()

        selection_controls = QWidget()
        bulk = QHBoxLayout(selection_controls)
        bulk.setContentsMargins(8, 0, 4, 0)
        bulk.setSpacing(8)
        self.odd_checkbox = QCheckBox("單數頁")
        self.even_checkbox = QCheckBox("雙數頁")
        for checkbox in (self.odd_checkbox, self.even_checkbox):
            checkbox.setTristate(True)
            checkbox.setEnabled(False)
            bulk.addWidget(checkbox)
        self.odd_checkbox.setToolTip("選取或取消原始頁碼的單數頁")
        self.even_checkbox.setToolTip("選取或取消原始頁碼的雙數頁")
        self.odd_checkbox.clicked.connect(lambda checked: self._toggle_parity(True, checked))
        self.even_checkbox.clicked.connect(lambda checked: self._toggle_parity(False, checked))
        self.toolbar.addWidget(selection_controls)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addSeparator()
        self.zoom_out_action = QAction("縮小", self)
        self.zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self.zoom_out_action.setToolTip("縮小（Ctrl+-）")
        self.zoom_out_action.triggered.connect(lambda: self._adjust_zoom(-25))
        self.addAction(self.zoom_out_action)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(150)
        self.zoom_slider.setAccessibleName("頁面顯示比例")
        self.zoom_slider.setToolTip("100% 以 96 DPI 顯示 PDF 頁面")
        self.zoom_slider.valueChanged.connect(self._zoom_changed)
        self.zoom_in_action = QAction("放大", self)
        self.zoom_in_action.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.zoom_in_action.setToolTip("放大（Ctrl++ / Ctrl+=）")
        self.zoom_in_action.triggered.connect(lambda: self._adjust_zoom(25))
        self.addAction(self.zoom_in_action)
        self.zoom_reset_action = QAction("100%", self)
        self.zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        self.zoom_reset_action.setToolTip(
            "頁面顯示比例：25%–200%\n"
            "拖曳右側滑桿調整比例。\n"
            "放大：Ctrl++ 或 Ctrl+=（每次增加 25 個百分點）\n"
            "縮小：Ctrl+-（每次減少 25 個百分點）\n"
            "回到 100%：點擊比例或按 Ctrl+0\n"
            "100% 以 96 DPI 顯示 PDF 頁面。"
        )
        self.zoom_reset_action.triggered.connect(lambda: self.zoom_slider.setValue(100))
        self.toolbar.addAction(self.zoom_reset_action)
        self.zoom_display = self.toolbar.widgetForAction(self.zoom_reset_action)
        self.zoom_display.setFixedWidth(64)
        self.zoom_display.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.toolbar.addWidget(self.zoom_slider)
        self._refresh_toolbar_icons()

    def _refresh_toolbar_icons(self) -> None:
        for action, kind in ((self.open_action, "open"), (self.export_action, "export"),
                             (self.split_action, "split")):
            action.setIcon(toolbar_icon(kind))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "zoom_reset_action"):
            self._refresh_toolbar_icons()

    def _update_window_title(self, path: Path | None = None) -> None:
        title = f"PDF 選頁重組工具 {__version__} 版"
        self.setWindowTitle(f"{path.resolve()} — {title}" if path is not None else title)

    def _adjust_zoom(self, delta: int) -> None:
        self.zoom_slider.setValue(self.zoom_slider.value() + delta)

    def current_document(self):
        return self.tabs.currentWidget() if hasattr(self, "tabs") else None

    def ordered_documents(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def output_selection(self) -> list[DocumentSelection]:
        documents = self.ordered_documents()
        included = [doc for doc in documents if doc.include_checkbox.isChecked()]
        if not included:
            current = self.current_document()
            included = [current] if current is not None else []
        return [DocumentSelection(doc.source_path, tuple(page for page in doc.page_order if page in doc.selected_pages))
                for doc in included if doc.ready and doc.selected_pages]

    def _tab_changed(self, _index: int) -> None:
        if self._closing:
            return
        doc = self.current_document()
        self._update_window_title(doc.source_path if doc is not None else None)
        if doc is not None:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(doc.zoom)
            self.zoom_slider.blockSignals(False)
            self.render_service.prioritize(doc.document_id)
            if doc.ready and (doc.render_generation < 0 or doc.render_timer.isActive()):
                doc._queue_all_renders()
            doc._reflow_grid()
        self._sync_controls()

    def _sync_controls(self, *_args) -> None:
        if not hasattr(self, "tabs") or self._closing:
            return
        doc = self.current_document()
        ready = doc is not None and doc.ready
        self._syncing_bulk = True
        for checkbox, odd in ((self.odd_checkbox, True), (self.even_checkbox, False)):
            checkbox.blockSignals(True)
            state = parity_state(doc.selected_pages, doc.page_count, odd) if ready else SelectionState.NONE
            checkbox.setCheckState({SelectionState.NONE: Qt.CheckState.Unchecked,
                                    SelectionState.PARTIAL: Qt.CheckState.PartiallyChecked,
                                    SelectionState.ALL: Qt.CheckState.Checked}[state])
            checkbox.setEnabled(ready and not self._export_running and (odd or doc.page_count >= 2))
            checkbox.blockSignals(False)
        self._syncing_bulk = False
        self.zoom_reset_action.setText(f"{self.zoom_slider.value()}%")
        self.zoom_out_action.setEnabled(self.zoom_slider.value() > 25)
        self.zoom_in_action.setEnabled(self.zoom_slider.value() < 200)
        enabled = bool(self.output_selection()) and not self._export_running
        self.export_action.setEnabled(enabled)
        self.split_action.setEnabled(enabled)
        if not self._export_running:
            count = sum(len(item.pages) for item in self.output_selection())
            self.statusBar().showMessage(
                f"目前檔案：已選取 {len(doc.selected_pages)} / {doc.page_count} 頁；輸出合計 {count} 頁"
                if ready else ("正在讀取 PDF…" if doc is not None else "就緒"))

    def _toggle_parity(self, odd: bool, checked: bool) -> None:
        doc = self.current_document()
        if doc is not None and doc.ready and not self._export_running:
            doc._toggle_parity(odd, checked)

    def _zoom_changed(self, value: int) -> None:
        doc = self.current_document()
        if doc is not None:
            doc.set_zoom(value)
        self._sync_controls()

    def _dropped_pdfs(self, event) -> list[Path]:
        if self._export_running:
            return []
        urls = event.mimeData().urls()
        if not urls or any(not url.isLocalFile() for url in urls):
            return []
        paths = [Path(url.toLocalFile()) for url in urls]
        return paths if all(path.suffix.lower() == ".pdf" and path.is_file() for path in paths) else []

    def dragEnterEvent(self, event) -> None:
        if self._dropped_pdfs(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        paths = self._dropped_pdfs(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.load_pdfs(paths)

    @Slot()
    def choose_pdf(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(self, "開啟 PDF", str(Path.home()), "PDF 檔案 (*.pdf)")
        if filenames:
            self.load_pdfs([Path(filename) for filename in filenames])

    def _new_document(self, path: Path):
        self._next_document_id += 1
        doc = DocumentView(self, self._next_document_id, path)
        self.documents[doc.document_id] = doc
        self.empty_label.hide()
        self.tabs.show()
        index = self.tabs.addTab(doc, path.stem)
        self.tabs.setTabToolTip(index, str(doc.source_path))
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, doc.include_checkbox)
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, doc.close_button)
        self.tabs.setCurrentIndex(index)
        return doc

    def load_pdf(self, path: Path) -> None:
        self.load_pdfs([path])

    def load_pdfs(self, paths: list[Path]) -> None:
        if self._export_running:
            return
        self._next_batch += 1
        batch = self._next_batch
        self._load_batches[batch] = {"pending": set(), "errors": []}
        for path in paths:
            path = Path(path).resolve()
            existing = next((doc for doc in self.documents.values() if doc.source_path == path), None)
            if existing is not None:
                self.tabs.setCurrentWidget(existing)
                continue
            doc = self._new_document(path)
            self._document_batches[doc.document_id] = batch
            self._load_batches[batch]["pending"].add(doc.document_id)
            task = LoadPdfTask(path, doc.document_id)
            self._active_tasks.add(task)
            task.signals.loaded.connect(self._pdf_loaded)
            task.signals.failed.connect(self._pdf_load_failed)
            task.signals.loaded.connect(lambda *_args, job=task: self._active_tasks.discard(job))
            task.signals.failed.connect(lambda *_args, job=task: self._active_tasks.discard(job))
            self.thread_pool.start(task)
        if not self._load_batches[batch]["pending"]:
            self._load_batches.pop(batch)

    def _finish_load(self, document_id: int, error: str | None = None) -> None:
        batch = self._document_batches.pop(document_id, None)
        if batch is None:
            return
        state = self._load_batches[batch]
        state["pending"].discard(document_id)
        if error:
            state["errors"].append(error)
        if not state["pending"]:
            self._load_batches.pop(batch)
            if state["errors"] and not self._closing:
                QMessageBox.critical(self, "部分 PDF 無法開啟", "\n\n".join(state["errors"]))

    @Slot(int, object, int)
    def _pdf_loaded(self, document_id: int, path: Path, page_count: int) -> None:
        doc = self.documents.get(document_id)
        if doc is not None and not self._closing:
            doc.loaded(page_count)
            if self.current_document() is doc:
                self._tab_changed(self.tabs.currentIndex())
            self._sync_controls()
        self._finish_load(document_id)

    @Slot(int, str)
    def _pdf_load_failed(self, document_id: int, message: str) -> None:
        doc = self.documents.get(document_id)
        error = f"{doc.source_path}\n{message}" if doc is not None else None
        if doc is not None:
            self.close_tab(self.tabs.indexOf(doc), force=True)
        self._finish_load(document_id, error)

    def close_tab(self, index: int, *, force: bool = False) -> None:
        if (self._export_running and not force) or index < 0:
            return
        doc = self.tabs.widget(index)
        if doc is None:
            return
        doc.render_timer.stop()
        doc.grid_host.finish_drag()
        self.render_service.cancel_pending(doc.document_id)
        for generation, document_id in list(self._render_documents.items()):
            if document_id == doc.document_id:
                self._render_documents.pop(generation)
        self.documents.pop(doc.document_id, None)
        self.tabs.removeTab(index)
        doc.deleteLater()
        if not self.tabs.count():
            self.tabs.hide()
            self.empty_label.show()
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(100)
            self.zoom_slider.blockSignals(False)
        self._sync_controls()

    @Slot(object)
    def _handle_render_message(self, payload) -> None:
        if not isinstance(payload, dict):
            return
        try:
            generation = int(payload.get("generation", -1))
        except (TypeError, ValueError):
            return
        doc = self.documents.get(self._render_documents.get(generation))
        if doc is not None and doc.render_generation == generation and not self._closing:
            doc._handle_render_message(payload)
        elif payload.get("type") == "page":
            path = Path(str(payload.get("path", "")))
            if path.parent == Path(self.preview_temp.name) and path.name.startswith(f"g{generation}-p"):
                path.unlink(missing_ok=True)
        if payload.get("type") in {"done", "error"}:
            self._render_documents.pop(generation, None)

    def _set_export_running(self, running: bool) -> None:
        self._export_running = running
        self.open_action.setEnabled(not running)
        self.tabs.setMovable(not running)
        for doc in self.documents.values():
            doc.include_checkbox.setEnabled(doc.ready and not running)
            doc.close_button.setEnabled(not running)
            for card in doc.page_cards:
                card.checkbox.setEnabled(not running)
        self._sync_controls()

    @Slot()
    def choose_output(self) -> None:
        self._choose_output(split=False)

    @Slot()
    def choose_split_output(self) -> None:
        self._choose_output(split=True)

    def _choose_output(self, *, split: bool) -> None:
        selections = self.output_selection()
        if not selections or self._export_running:
            return
        suggested = default_output_path(selections[0].source)
        filename, _ = QFileDialog.getSaveFileName(
            self, "拆分選取頁面：指定檔名，將自動附加序號" if split else "輸出選取頁面",
            str(suggested), "PDF 檔案 (*.pdf)", "",
            QFileDialog.Option.DontConfirmOverwrite if split else QFileDialog.Option(0),
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".pdf":
            destination = destination.with_suffix(".pdf")
        outputs = split_output_paths(destination, sum(len(item.pages) for item in selections)) if split else [destination]
        if {doc.source_path for doc in self.documents.values()}.intersection(path.resolve() for path in outputs):
            QMessageBox.warning(self, "無法輸出", "輸出檔案不可覆蓋來源 PDF。")
            return
        overwrite = False
        if split:
            existing = [path for path in outputs if path.exists()]
            if existing:
                answer = QMessageBox.question(
                    self, "覆蓋單頁檔案",
                    f"已有 {len(existing)} 個同名單頁檔案，例如：\n{existing[0]}\n\n是否覆蓋？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                overwrite = True
        self._start_export(destination, split=split, overwrite=overwrite)

    def _start_export(self, destination: Path, *, split: bool = False, overwrite: bool = False) -> None:
        selections = self.output_selection()
        if not selections or self._export_running:
            return
        self._export_id += 1
        self._set_export_running(True)
        self._export_split = split
        self.statusBar().showMessage("正在拆分單頁 PDF…" if split else "正在輸出 PDF…")
        task = ExportPdfTask(
            selections,
            destination,
            self._export_id,
            split=split, overwrite=overwrite,
            protected_sources=tuple(doc.source_path for doc in self.documents.values()),
        )
        self._active_tasks.add(task)
        task.signals.completed.connect(self._export_completed)
        task.signals.failed.connect(self._export_failed)
        task.signals.completed.connect(lambda *_args, job=task: self._active_tasks.discard(job))
        task.signals.failed.connect(lambda *_args, job=task: self._active_tasks.discard(job))
        self.thread_pool.start(task)

    @Slot(int, object, int)
    def _export_completed(self, session: int, destination: Path, count: int) -> None:
        if session != self._export_id or self._closing:
            return
        self._set_export_running(False)
        self.statusBar().showMessage(f"輸出完成：{destination}")
        if self._export_split:
            outputs = split_output_paths(destination, count)
            message = f"已拆分為 {count} 個單頁 PDF：\n{outputs[0]}"
            if count > 1:
                message += f"\n…\n{outputs[-1]}"
        else:
            message = f"已輸出 {count} 頁至：\n{destination}"
        QMessageBox.information(self, "輸出完成", message)

    @Slot(int, str)
    def _export_failed(self, session: int, message: str) -> None:
        if session != self._export_id or self._closing:
            return
        self._set_export_running(False)
        self.statusBar().showMessage("輸出失敗")
        QMessageBox.critical(self, "輸出失敗", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        for doc in self.documents.values():
            doc.render_timer.stop()
            doc.grid_host.finish_drag()
        self.render_service.close()
        self.thread_pool.clear()
        self.thread_pool.waitForDone()
        self.preview_temp.cleanup()
        event.accept()


def load_app_icon() -> QIcon:
    return QIcon(str(files("pdfpick").joinpath("assets", "pdfpick.png")))


def configure_application(app: QApplication) -> None:
    app.setApplicationName("PDF 選頁重組工具")
    app.setOrganizationName("PDFPick")
    app.setStyle("Fusion")
    app.setWindowIcon(load_app_icon())
    available = set(QFontDatabase.families())
    for family in (
        "Microsoft JhengHei UI",
        "Microsoft JhengHei",
        "Noto Sans TC",
        "Arial",
    ):
        if family in available:
            app.setFont(QFont(family, 10))
            break


def main() -> int:
    render_backend = start_render_backend()
    app = QApplication(sys.argv)
    configure_application(app)
    theme = ThemeController(app)
    window = MainWindow(render_backend)
    window.show()
    window._theme_controller = theme
    return app.exec()
