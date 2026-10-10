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
    QVBoxLayout,
    QWidget,
)

from pdfpick.core import (
    SelectionState,
    default_output_path,
    parity_state,
    set_parity,
    split_output_paths,
)
from pdfpick import __version__
from pdfpick.icons import toolbar_icon
from pdfpick.theme import ThemeController
from pdfpick.renderer import RenderService, start_render_backend
from pdfpick.widgets import PageCard, PageGrid
from pdfpick.workers import ExportPdfTask, LoadPdfTask


class MainWindow(QMainWindow):
    REFERENCE_PAGE_WIDTH_POINTS = 595
    SCREEN_DPI = 96
    PDF_DPI = 72

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
        backend = render_backend if render_backend is not None else start_render_backend()
        self.render_service = RenderService(backend, self)
        self.render_service.message.connect(self._handle_render_message)
        self._render_received: set[int] = set()
        self.source_path: Path | None = None
        self.page_count = 0
        self.selected_pages: set[int] = set()
        self.page_order: list[int] = []
        self.page_cards: list[PageCard] = []
        self.session_id = 0
        self.render_generation = 0
        self._syncing_bulk = False
        self._export_running = False
        self._active_tasks: set[object] = set()
        self._render_pending = 0
        self._render_done_generation = -1

        self._build_ui()
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(250)
        self.render_timer.timeout.connect(self._queue_all_renders)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(12)

        self._build_toolbar()

        middle = QWidget()
        middle_layout = QVBoxLayout(middle)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(8)

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
        self.empty_label = QLabel("請先選取 PDF 檔案，或將 PDF 拖曳到視窗")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(self.empty_label, 0, 0)
        self.scroll_area.setWidget(self.grid_host)
        middle_layout.addWidget(self.scroll_area, 1)
        root.addWidget(middle, 1)

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

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._reflow_grid)
        return super().eventFilter(watched, event)

    def _dropped_pdf(self, event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> Path | None:
        if not self.open_action.isEnabled():
            return None
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        return path if path.suffix.lower() == ".pdf" and path.is_file() else None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_pdf(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._dropped_pdf(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        path = self._dropped_pdf(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.load_pdf(path)

    @Slot()
    def choose_pdf(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, "選取 PDF", str(Path.home()), "PDF 檔案 (*.pdf)"
        )
        if filename:
            self.load_pdf(Path(filename))

    def load_pdf(self, path: Path) -> None:
        self.session_id += 1
        session = self.session_id
        self._reset_document()
        self._update_window_title(path)
        self.open_action.setEnabled(False)
        self.statusBar().showMessage("正在讀取 PDF…")
        task = LoadPdfTask(path, session)
        self._keep_task(task)
        task.signals.loaded.connect(self._pdf_loaded)
        task.signals.failed.connect(self._pdf_load_failed)
        task.signals.loaded.connect(lambda *_args, job=task: self._release_task(job))
        task.signals.failed.connect(lambda *_args, job=task: self._release_task(job))
        self.thread_pool.start(task)

    def _keep_task(self, task: object) -> None:
        self._active_tasks.add(task)

    def _release_task(self, task: object) -> None:
        self._active_tasks.discard(task)

    @Slot(int, object, int)
    def _pdf_loaded(self, session: int, path: Path, page_count: int) -> None:
        if session != self.session_id:
            return
        self.source_path = Path(path)
        self._update_window_title(self.source_path)
        self.page_count = page_count
        self.open_action.setEnabled(True)
        self.empty_label.hide()
        self._create_page_cards()
        self.odd_checkbox.setEnabled(True)
        self.even_checkbox.setEnabled(page_count >= 2)
        self._sync_bulk_checks()
        self.statusBar().showMessage(f"已載入 {page_count} 頁")
        self._queue_all_renders()

    @Slot(int, str)
    def _pdf_load_failed(self, session: int, message: str) -> None:
        if session != self.session_id:
            return
        self.open_action.setEnabled(True)
        self._update_window_title()
        self.statusBar().showMessage("讀取失敗")
        QMessageBox.critical(self, "無法開啟 PDF", message)

    def _reset_document(self) -> None:
        self.grid_host.finish_drag()
        self.render_generation += 1
        self._render_pending = 0
        self._reset_render_state()
        self.source_path = None
        self.page_count = 0
        self.selected_pages.clear()
        self.page_order.clear()
        self.page_cards.clear()
        while (item := self.grid.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None and widget is not self.empty_label:
                widget.deleteLater()
        self.grid.addWidget(self.empty_label, 0, 0)
        self.empty_label.show()
        self.odd_checkbox.setEnabled(False)
        self.even_checkbox.setEnabled(False)
        self._sync_bulk_checks()
        self.export_action.setEnabled(False)
        self.split_action.setEnabled(False)

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
        return self.zoom_slider.value() / 100 * self.SCREEN_DPI / self.PDF_DPI

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
        if self._export_running or source_index not in self.page_order:
            return
        self.page_order.remove(source_index)
        self.page_order.insert(insertion, source_index)
        self._reflow_grid()
        self.statusBar().showMessage(
            f"已調整第 {source_index + 1} 頁的預覽與輸出順序"
        )

    @Slot(int, int)
    def _move_page(self, source_index: int, target_index: int) -> None:
        if self._export_running or source_index == target_index:
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
        self.statusBar().showMessage(
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
        if self._syncing_bulk:
            return
        self.selected_pages = set_parity(
            self.selected_pages, self.page_count, odd, checked
        )
        for card in self.page_cards:
            card.set_selected(card.page_index in self.selected_pages)
        self._selection_updated()

    def _selection_updated(self) -> None:
        self._sync_bulk_checks()
        self.export_action.setEnabled(bool(self.selected_pages) and not self._export_running)
        self.split_action.setEnabled(bool(self.selected_pages) and not self._export_running)
        self.statusBar().showMessage(
            f"已選取 {len(self.selected_pages)} / {self.page_count} 頁"
        )

    def _sync_bulk_checks(self) -> None:
        self._syncing_bulk = True
        try:
            self._set_bulk_state(self.odd_checkbox, parity_state(
                self.selected_pages, self.page_count, True
            ))
            self._set_bulk_state(self.even_checkbox, parity_state(
                self.selected_pages, self.page_count, False
            ))
        finally:
            self._syncing_bulk = False

    @staticmethod
    def _set_bulk_state(checkbox: QCheckBox, state: SelectionState) -> None:
        mapping = {
            SelectionState.NONE: Qt.CheckState.Unchecked,
            SelectionState.PARTIAL: Qt.CheckState.PartiallyChecked,
            SelectionState.ALL: Qt.CheckState.Checked,
        }
        checkbox.blockSignals(True)
        checkbox.setCheckState(mapping[state])
        checkbox.blockSignals(False)

    @Slot(int)
    def _zoom_changed(self, value: int) -> None:
        self.zoom_reset_action.setText(f"{value}%")
        self.zoom_out_action.setEnabled(value > self.zoom_slider.minimum())
        self.zoom_in_action.setEnabled(value < self.zoom_slider.maximum())
        if self.page_cards:
            self.render_timer.start()

    @Slot()
    def _queue_all_renders(self) -> None:
        if self.source_path is None:
            return
        self.render_generation += 1
        generation = self.render_generation
        self._render_pending = self.page_count
        self._render_done_generation = -1
        self._render_received.clear()
        width = self._target_preview_width()
        for card in self.page_cards:
            card.set_target_width(width)
        self._reflow_grid()
        self.statusBar().showMessage("正在產生頁面預覽…")
        self._reset_render_state()
        self.render_service.request(
            self.source_path,
            self._preview_scale(),
            Path(self.preview_temp.name),
            generation,
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
            self.statusBar().showMessage(
                f"已載入 {self.page_count} 頁；已選取 {len(self.selected_pages)} 頁"
            )
        elif kind == "error":
            for page_index, card in enumerate(self.page_cards):
                if page_index not in self._render_received:
                    card.set_render_error()
            self.statusBar().showMessage("部分頁面無法產生預覽")
            QMessageBox.warning(
                self, "預覽失敗", f"無法完成頁面預覽：\n{payload.get('message', '')}"
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
            self.statusBar().showMessage(
                f"已載入 {self.page_count} 頁；已選取 {len(self.selected_pages)} 頁"
            )

    def _reset_render_state(self) -> None:
        self._render_received.clear()

    @Slot()
    def choose_output(self) -> None:
        self._choose_output(split=False)

    @Slot()
    def choose_split_output(self) -> None:
        self._choose_output(split=True)

    def _choose_output(self, *, split: bool) -> None:
        if self.source_path is None or not self.selected_pages or self._export_running:
            return
        suggested = default_output_path(self.source_path)
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
        outputs = split_output_paths(destination, len(self.selected_pages)) if split else [destination]
        if self.source_path.resolve() in [path.resolve() for path in outputs]:
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
        assert self.source_path is not None
        self._export_running = True
        self._export_split = split
        self.export_action.setEnabled(False)
        self.split_action.setEnabled(False)
        self.open_action.setEnabled(False)
        self.statusBar().showMessage("正在拆分單頁 PDF…" if split else "正在輸出 PDF…")
        task = ExportPdfTask(
            self.source_path,
            destination,
            [page for page in self.page_order if page in self.selected_pages],
            self.session_id,
            split=split, overwrite=overwrite,
        )
        self._keep_task(task)
        task.signals.completed.connect(self._export_completed)
        task.signals.failed.connect(self._export_failed)
        task.signals.completed.connect(lambda *_args, job=task: self._release_task(job))
        task.signals.failed.connect(lambda *_args, job=task: self._release_task(job))
        self.thread_pool.start(task)

    @Slot(int, object, int)
    def _export_completed(self, session: int, destination: Path, count: int) -> None:
        if session != self.session_id:
            return
        self._export_running = False
        self.open_action.setEnabled(True)
        self.export_action.setEnabled(bool(self.selected_pages))
        self.split_action.setEnabled(bool(self.selected_pages))
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
        if session != self.session_id:
            return
        self._export_running = False
        self.open_action.setEnabled(True)
        self.export_action.setEnabled(bool(self.selected_pages))
        self.split_action.setEnabled(bool(self.selected_pages))
        self.statusBar().showMessage("輸出失敗")
        QMessageBox.critical(self, "輸出失敗", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.session_id += 1
        self.render_service.close()
        self.thread_pool.clear()
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
