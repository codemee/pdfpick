from __future__ import annotations

from repdf.strings import tr, localize_text

import sys
import tempfile
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, QSize, Qt, QThreadPool, QTimer, Slot
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
    QAbstractButton,
    QAbstractSlider,
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

from repdf.core import (
    SelectionState,
    default_output_path,
    parity_state,
    set_parity,
    split_output_paths,
    DocumentSelection,
)
from repdf import __version__
from repdf.icons import toolbar_icon
from repdf.theme import ThemeController
from repdf.preferences import LanguageController, migrate_preferences
from repdf.renderer import RenderService, start_render_backend
from repdf.widgets import PageCard, PageGrid
from repdf.preview import FullscreenPreview
from repdf.workers import ExportPdfTask, LoadPdfTask


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
        self.fit_mode = False
        self.fit_page_index = 0
        self._fit_navigation_pending = False
        self.focused_page = None
        self.page_sizes = {}
        self.ready = False
        self.render_generation = -1
        self._render_received = set()
        self._render_pending = 0
        self._render_done_generation = -1
        self.include_checkbox = QCheckBox()
        self.include_checkbox.setToolTip(tr('勾選此檔案以加入重組或拆分；未勾選任何標籤時僅輸出目前檔案'))
        self.include_checkbox.setEnabled(False)
        self.include_checkbox.toggled.connect(owner._sync_controls)
        self.close_button = QToolButton()
        self.close_button.setText("×")
        self.close_button.setToolTip(tr('關閉此檔案'))
        self.close_button.setFixedSize(22, 22)
        self.close_button.clicked.connect(lambda: owner.close_tab(owner.tabs.indexOf(self)))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        horizontal = self.scroll_area.horizontalScrollBar()
        horizontal.rangeChanged.connect(lambda minimum, maximum:
                                        horizontal.setValue((minimum + maximum) // 2))
        self.scroll_area.viewport().installEventFilter(self)
        self.grid_host = PageGrid()
        self.grid_host.insertion_requested.connect(self._insert_page)
        self.grid_host.drag_finished.connect(self._reflow_grid)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(12, 12, 12, 12)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.empty_label = QLabel(tr('正在讀取 PDF…'))
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grid.addWidget(self.empty_label, 0, 0)
        self.scroll_area.setWidget(self.grid_host)
        root.addWidget(self.scroll_area)
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(250)
        self.render_timer.timeout.connect(self._queue_all_renders)
        self.fit_timer = QTimer(self)
        self.fit_timer.setSingleShot(True)
        self.fit_timer.setInterval(150)
        self.fit_timer.timeout.connect(self._apply_fit)

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
            if self.fit_mode:
                self.fit_timer.start()
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
            card.focused.connect(self._focus_page)
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
        if self.fit_mode:
            columns = 1
        for position, page_index in enumerate(self.page_order):
            card = self.page_cards[page_index]
            self.grid.addWidget(card, position // columns, position % columns,
                                Qt.AlignmentFlag.AlignHCenter)
        self.grid.activate()

    @Slot(int, int)
    def _insert_page(self, source_index: int, insertion: int) -> None:
        if self.owner._export_running or source_index not in self.page_order:
            return
        self.page_order.remove(source_index)
        self.page_order.insert(insertion, source_index)
        self._reflow_grid()
        self.show_status(
            tr('已調整第 {p0} 頁的預覽與輸出順序', p0=source_index + 1)
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
            tr('已調整第 {p0} 頁的預覽與輸出順序', p0=source_index + 1)
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
        was_fit = self.fit_mode
        self.fit_mode = False
        self._fit_navigation_pending = False
        self.fit_timer.stop()
        if was_fit:
            self._reflow_grid()
        if self.zoom == value:
            return
        self.zoom = value
        if self.page_cards:
            self.render_timer.start()

    def _focus_page(self, page_index: int) -> None:
        self.focused_page = page_index

    def preview_page_index(self, *, prefer_focused=True) -> int:
        visible = self.scroll_area.viewport().rect().translated(
            self.scroll_area.horizontalScrollBar().value(), self.scroll_area.verticalScrollBar().value())
        if prefer_focused and self.focused_page is not None and self.page_cards[self.focused_page].geometry().intersects(visible):
            return self.focused_page
        return min(self.page_order, key=lambda index:
                   (self.page_cards[index].geometry().center() - visible.center()).manhattanLength())

    def fit_page(self) -> None:
        index = self.preview_page_index()
        if index not in self.page_sizes:
            return
        self.fit_page_index = index
        self.fit_mode = True
        self._apply_fit()

    def _apply_fit(self) -> None:
        if not self.fit_mode or self.owner._closing:
            return
        card = self.page_cards[self.fit_page_index]
        points = self.page_sizes.get(self.fit_page_index)
        if points is None:
            return
        width, height = points
        margins = self.grid.contentsMargins()
        chrome = max(0, card.sizeHint().height() - card.preview.height())
        available_width = max(1, self.scroll_area.viewport().width() - margins.left() - margins.right() - 26)
        # Grid margins surround the entire document, not each fitted page.
        # Fit the card to the viewport and scroll it into alignment separately.
        available_height = max(1, self.scroll_area.viewport().height() - chrome - 2)
        zoom = round(min(available_width / width, available_height / height) * self.PDF_DPI / self.SCREEN_DPI * 100, 2)
        if abs(zoom - self.zoom) > 0.05:
            self.zoom = zoom
            self.render_timer.start()
        self._reflow_grid()
        self.owner._sync_controls()
        QTimer.singleShot(0, self._scroll_to_fit_page)

    def _scroll_to_fit_page(self) -> None:
        if not self.fit_mode or self.owner._closing:
            return
        card = self.page_cards[self.fit_page_index]
        viewport = self.scroll_area.viewport()
        self.scroll_area.verticalScrollBar().setValue(
            card.y() + (card.height() - viewport.height()) // 2)
        self.scroll_area.horizontalScrollBar().setValue(
            card.x() + (card.width() - viewport.width()) // 2)
        self._fit_navigation_pending = False

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
        self.show_status(tr('正在產生頁面預覽…'))
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
                tr('已載入 {p0} 頁；已選取 {p1} 頁', p0=self.page_count, p1=len(self.selected_pages))
            )
        elif kind == "error":
            for page_index, card in enumerate(self.page_cards):
                if page_index not in self._render_received:
                    card.set_render_error()
            self.show_status(tr('部分頁面無法產生預覽'))
            QMessageBox.warning(
                self.owner, tr('預覽失敗'), tr('無法完成頁面預覽：\n{p0}', p0=payload.get('message', ''))
            )

    def _accept_render_page(self, payload: dict[str, object]) -> None:
        try:
            page_index = int(payload["page"])
            image_path = Path(payload["path"])
        except (KeyError, TypeError, ValueError):
            return
        image = QImage(str(image_path)).copy()
        if 0 <= page_index < len(self.page_cards) and not image.isNull():
            self.page_sizes[page_index] = (
                float(payload.get("width_points", image.width() / self._preview_scale())),
                float(payload.get("height_points", image.height() / self._preview_scale())),
            )
            self.page_cards[page_index].set_image(image)
            self._reflow_grid()
            if self.fit_mode and page_index == self.fit_page_index:
                self.fit_timer.start()
        elif 0 <= page_index < len(self.page_cards):
            self.page_cards[page_index].set_render_error()
        image_path.unlink(missing_ok=True)
        if page_index not in self._render_received:
            self._render_received.add(page_index)
            self._render_pending -= 1
        if self._render_pending == 0:
            self.show_status(
                tr('已載入 {p0} 頁；已選取 {p1} 頁', p0=self.page_count, p1=len(self.selected_pages))
            )
        self.owner._sync_controls()
        if self.fit_mode and page_index == self.fit_page_index:
            QTimer.singleShot(0, self._scroll_to_fit_page)

    def _reset_render_state(self) -> None:
        self._render_received.clear()



class MainWindow(QMainWindow):
    def __init__(self, render_backend=None) -> None:
        super().__init__()
        self.settings = QSettings("repdf", "repdf")
        migrate_preferences(self.settings, QSettings("PDFPick", "PDFPick"))
        self.language_controller = LanguageController(self.settings.value("ui/language", "system"), self)
        self._theme_controller = ThemeController(QApplication.instance(), self.settings.value("ui/theme", "system"), self)
        self._update_window_title()
        self.setWindowIcon(load_app_icon())
        self.resize(1040, 760)
        self.setMinimumSize(720, 520)
        self.setAcceptDrops(True)
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(4)
        self.preview_temp = tempfile.TemporaryDirectory(prefix="repdf-preview-")
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
        self._fullscreen_preview = None
        self._build_toolbar()
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 12)
        self.empty_label = QLabel(tr('請先開啟 PDF 檔案，或將多個 PDF 拖曳到視窗'))
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
        self.statusBar().showMessage(tr('就緒'))
        self.language_controller.changed.connect(self._retranslate)
        self._update_preference_actions()

        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        keys = (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
                Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
        if (not self._closing and isinstance(watched, QWidget) and watched.window() is self
                and event.type() == QEvent.Type.KeyPress and not event.modifiers()
                and event.key() in keys):
            self._navigate_preview(event.key())
            return True
        return super().eventFilter(watched, event)

    def _navigate_preview(self, key) -> None:
        doc = self.current_document()
        if doc is None or not doc.ready:
            return
        previous = key in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp)
        if doc.fit_mode:
            pending = doc._fit_navigation_pending or doc.render_timer.isActive() or doc._render_pending > 0
            current = doc.fit_page_index if pending else doc.preview_page_index(prefer_focused=False)
            doc.fit_page_index = current
            doc.focused_page = current
            position = doc.page_order.index(current) + (-1 if previous else 1)
            if 0 <= position < len(doc.page_order):
                doc.fit_page_index = doc.page_order[position]
                doc.focused_page = doc.fit_page_index
                doc._fit_navigation_pending = True
                doc._apply_fit()
            return
        horizontal = key in (Qt.Key.Key_Left, Qt.Key.Key_Right)
        scrollbar = doc.scroll_area.horizontalScrollBar() if horizontal else doc.scroll_area.verticalScrollBar()
        paging = key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)
        action = (QAbstractSlider.SliderAction.SliderPageStepSub if previous else QAbstractSlider.SliderAction.SliderPageStepAdd) if paging else (
            QAbstractSlider.SliderAction.SliderSingleStepSub if previous else QAbstractSlider.SliderAction.SliderSingleStepAdd)
        scrollbar.triggerAction(action)

    def _build_toolbar(self) -> None:
        self.toolbar = QToolBar(tr('檔案與顯示'), self)
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.toolbar.setIconSize(QSize(18, 18))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(self.toolbar)

        self.open_action = QAction(tr('開啟 PDF'), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.setToolTip(tr('開啟 PDF（Ctrl+O）'))
        self.open_action.triggered.connect(self.choose_pdf)
        self.toolbar.addAction(self.open_action)
        self.export_action = QAction(tr('輸出選取頁面'), self)
        self.export_action.setShortcuts([QKeySequence("Ctrl+S"), QKeySequence("Ctrl+Shift+S")])
        self.export_action.setToolTip(tr('輸出選取頁面為新 PDF（Ctrl+S / Ctrl+Shift+S）'))
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self.choose_output)
        self.toolbar.addAction(self.export_action)
        self.split_action = QAction(tr('拆分選取頁面'), self)
        self.split_action.setToolTip(tr('拆分選取頁面：依目前順序存成單頁 PDF，檔名附加補零序號'))
        self.split_action.setEnabled(False)
        self.split_action.triggered.connect(self.choose_split_output)
        self.toolbar.addAction(self.split_action)
        self.toolbar.addSeparator()

        selection_controls = QWidget()
        bulk = QHBoxLayout(selection_controls)
        bulk.setContentsMargins(8, 0, 4, 0)
        bulk.setSpacing(8)
        self.odd_checkbox = QCheckBox(tr('單數頁'))
        self.even_checkbox = QCheckBox(tr('雙數頁'))
        for checkbox in (self.odd_checkbox, self.even_checkbox):
            checkbox.setTristate(True)
            checkbox.setEnabled(False)
            bulk.addWidget(checkbox)
        self.odd_checkbox.setToolTip(tr('選取或取消原始頁碼的單數頁'))
        self.even_checkbox.setToolTip(tr('選取或取消原始頁碼的雙數頁'))
        self.odd_checkbox.clicked.connect(lambda checked: self._toggle_parity(True, checked))
        self.even_checkbox.clicked.connect(lambda checked: self._toggle_parity(False, checked))
        self.toolbar.addWidget(selection_controls)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addSeparator()
        self.zoom_out_action = QAction(tr('縮小'), self)
        self.zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self.zoom_out_action.setToolTip(tr('縮小（Ctrl+-）'))
        self.zoom_out_action.triggered.connect(lambda: self._adjust_zoom(-25))
        self.addAction(self.zoom_out_action)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(25, 200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(150)
        self.zoom_slider.setAccessibleName(tr('頁面顯示比例'))
        self.zoom_slider.setToolTip(tr('100% 以 96 DPI 顯示 PDF 頁面'))
        self.zoom_slider.valueChanged.connect(self._zoom_changed)
        self.zoom_in_action = QAction(tr('放大'), self)
        self.zoom_in_action.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.zoom_in_action.setToolTip(tr('放大（Ctrl++ / Ctrl+=）'))
        self.zoom_in_action.triggered.connect(lambda: self._adjust_zoom(25))
        self.addAction(self.zoom_in_action)
        self.zoom_reset_action = QAction("100%", self)
        self.zoom_reset_action.setShortcut(QKeySequence("Ctrl+0"))
        self.zoom_reset_action.setToolTip(
            tr('頁面顯示比例：25%–200%\n拖曳右側滑桿調整比例。\n放大：Ctrl++ 或 Ctrl+=（每次增加 25 個百分點）\n縮小：Ctrl+-（每次減少 25 個百分點）\n回到 100%：點擊比例或按 Ctrl+0\n100% 以 96 DPI 顯示 PDF 頁面。')
        )
        self.zoom_reset_action.triggered.connect(lambda: self._set_manual_zoom(100))
        self.toolbar.addAction(self.zoom_reset_action)
        self.zoom_display = self.toolbar.widgetForAction(self.zoom_reset_action)
        self.zoom_display.setFixedWidth(64)
        self.zoom_display.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.toolbar.addWidget(self.zoom_slider)
        self.fit_action = QAction("Fit", self)
        self.fit_action.setCheckable(True)
        self.fit_action.setToolTip(tr("Fit：將目前單頁等比例縮放至預覽區，視窗調整時自動適應"))
        self.fit_action.triggered.connect(self._fit_page)
        self.toolbar.addAction(self.fit_action)
        self.fullscreen_action = QAction(tr("全螢幕單頁"), self)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.setToolTip(tr("全螢幕單頁（F11）；Esc 結束，方向鍵／Page Up／Page Down 切頁，可勾選頁面"))
        self.fullscreen_action.triggered.connect(lambda: self._show_fullscreen_preview("single"))
        self.toolbar.addAction(self.fullscreen_action)
        self.spread_action = QAction(tr("全螢幕對頁"), self)
        self.spread_action.setToolTip(tr("全螢幕對頁：依目前順序兩頁並排；Esc 結束，方向鍵／Page Up／Page Down 切頁，可勾選頁面"))
        self.spread_action.triggered.connect(lambda: self._show_fullscreen_preview("spread"))
        self.toolbar.addAction(self.spread_action)
        self.cover_action = QAction(tr("全螢幕封面＋對頁"), self)
        self.cover_action.setToolTip(tr("全螢幕封面＋對頁：第一頁單獨顯示，其餘兩頁並排；Esc 結束，方向鍵／Page Up／Page Down 切頁，可勾選頁面"))
        self.cover_action.triggered.connect(lambda: self._show_fullscreen_preview("cover"))
        self.toolbar.addAction(self.cover_action)
        self.toolbar.addSeparator()
        self.language_action = QAction(self)
        self.language_action.triggered.connect(self._cycle_language)
        self.toolbar.addAction(self.language_action)
        self.theme_action = QAction(self)
        self.theme_action.triggered.connect(self._cycle_theme)
        self.toolbar.addAction(self.theme_action)
        self._refresh_toolbar_icons()

    def _refresh_toolbar_icons(self) -> None:
        for action, kind in ((self.open_action, "open"), (self.export_action, "export"),
                             (self.split_action, "split"), (self.fit_action, "fit"),
                             (self.fullscreen_action, "fullscreen"),
                             (self.spread_action, "fullscreen_spread"),
                             (self.cover_action, "fullscreen_cover")):
            action.setIcon(toolbar_icon(kind))
        if hasattr(self, "language_action"):
            self._update_preference_actions()

    def _update_preference_actions(self) -> None:
        language = self.language_controller
        language_names = {"system": tr("跟隨系統"), "zh": tr("中文"), "en": "English"}
        theme_names = {"system": tr("跟隨系統"), "light": tr("淺色"), "dark": tr("深色")}
        self.language_action.setText(tr("介面語言"))
        self.language_action.setIcon(toolbar_icon("language_" + language.mode))
        self.language_action.setToolTip(tr("介面語言：{mode}（目前：{language}）\n點擊依序切換：跟隨系統 → 中文 → English",
                                          mode=language_names[language.mode], language=language_names[language.language]))
        self.theme_action.setText(tr("介面配色"))
        self.theme_action.setIcon(toolbar_icon("theme_" + self._theme_controller.mode))
        self.theme_action.setToolTip(tr("介面配色：{mode}\n點擊依序切換：跟隨系統 → 淺色 → 深色",
                                      mode=theme_names[self._theme_controller.mode]))

    def _cycle_language(self) -> None:
        modes = ("system", "zh", "en")
        mode = modes[(modes.index(self.language_controller.mode) + 1) % 3]
        self.settings.setValue("ui/language", mode)
        self.language_controller.set_mode(mode)

    def _cycle_theme(self) -> None:
        modes = ("system", "light", "dark")
        mode = modes[(modes.index(self._theme_controller.mode) + 1) % 3]
        self.settings.setValue("ui/theme", mode)
        self._theme_controller.set_mode(mode)
        self._update_preference_actions()

    def _retranslate(self) -> None:
        status = localize_text(self.statusBar().currentMessage())
        for widget in self.findChildren(QLabel) + self.findChildren(QAbstractButton) + self.findChildren(QAction):
            if isinstance(widget, QLabel) and not widget.pixmap().isNull():
                continue
            text = localize_text(widget.text())
            if text != widget.text():
                widget.setText(text)
        for widget in self.findChildren(QWidget) + self.findChildren(QAction):
            widget.setToolTip(localize_text(widget.toolTip()))
            if isinstance(widget, QWidget):
                widget.setAccessibleName(localize_text(widget.accessibleName()))
        self.toolbar.setWindowTitle(localize_text(self.toolbar.windowTitle()))
        self._update_window_title()
        self._sync_controls()
        self.statusBar().showMessage(status)
        self._update_preference_actions()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "zoom_reset_action"):
            self._refresh_toolbar_icons()
        if event.type() == QEvent.Type.LocaleChange and hasattr(self, "language_controller"):
            if self.language_controller.mode == "system":
                self.language_controller.refresh()

    def _update_window_title(self) -> None:
        self.setWindowTitle(f"RePDF {__version__}")

    def _adjust_zoom(self, delta: int) -> None:
        doc = self.current_document()
        value = doc.zoom if doc is not None else self.zoom_slider.value()
        self._set_manual_zoom(max(25, min(200, round(value + delta))))

    def _set_manual_zoom(self, value: int) -> None:
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(value)
        self.zoom_slider.blockSignals(False)
        self._zoom_changed(value)

    def _fit_page(self) -> None:
        doc = self.current_document()
        if doc is not None and doc.ready:
            doc.fit_page()

    def _show_fullscreen_preview(self, mode="single") -> None:
        doc = self.current_document()
        if doc is None or not doc.ready or not doc.page_sizes:
            return
        if self._fullscreen_preview is not None:
            return
        viewer = FullscreenPreview(self, doc, doc.preview_page_index(), mode)
        self._fullscreen_preview = viewer
        viewer.setGeometry(self.screen().geometry())
        viewer.showFullScreen()
        viewer.activateWindow()
        viewer.setFocus()

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
        self._update_window_title()
        if doc is not None:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(round(doc.zoom))
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
        zoom = doc.zoom if ready else self.zoom_slider.value()
        if ready:
            self.zoom_slider.blockSignals(True)
            self.zoom_slider.setValue(round(zoom))
            self.zoom_slider.blockSignals(False)
        self.zoom_reset_action.setText(f"{zoom:g}%")
        self.fit_action.setChecked(ready and doc.fit_mode)
        available = ready and bool(doc.page_sizes)
        self.fit_action.setEnabled(available)
        self.fullscreen_action.setEnabled(available)
        self.spread_action.setEnabled(available)
        self.cover_action.setEnabled(available)
        self.zoom_out_action.setEnabled(zoom > 25)
        self.zoom_in_action.setEnabled(zoom < 200)
        enabled = bool(self.output_selection()) and not self._export_running
        self.export_action.setEnabled(enabled)
        self.split_action.setEnabled(enabled)
        if not self._export_running:
            count = sum(len(item.pages) for item in self.output_selection())
            self.statusBar().showMessage(
                tr('目前檔案：已選取 {p0} / {p1} 頁；輸出合計 {p2} 頁', p0=len(doc.selected_pages), p1=doc.page_count, p2=count)
                if ready else (tr('正在讀取 PDF…') if doc is not None else tr('就緒')))

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
        filenames, _ = QFileDialog.getOpenFileNames(self, tr('開啟 PDF'), str(Path.home()), tr('PDF 檔案 (*.pdf)'), "", QFileDialog.Option.DontUseNativeDialog)
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
                QMessageBox.critical(self, tr('部分 PDF 無法開啟'), "\n\n".join(state["errors"]))

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
        doc.fit_timer.stop()
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
        viewer = self._fullscreen_preview
        if viewer is not None and viewer.render_generation == generation:
            viewer.accept_render(payload)
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
            self, tr('拆分選取頁面：指定檔名，將自動附加序號') if split else tr('輸出選取頁面'),
            str(suggested), tr('PDF 檔案 (*.pdf)'), "",
            QFileDialog.Option.DontUseNativeDialog | (QFileDialog.Option.DontConfirmOverwrite if split else QFileDialog.Option(0)),
        )
        if not filename:
            return
        destination = Path(filename)
        if destination.suffix.lower() != ".pdf":
            destination = destination.with_suffix(".pdf")
        outputs = split_output_paths(destination, sum(len(item.pages) for item in selections)) if split else [destination]
        if {doc.source_path for doc in self.documents.values()}.intersection(path.resolve() for path in outputs):
            QMessageBox.warning(self, tr('無法輸出'), tr('輸出檔案不可覆蓋來源 PDF。'))
            return
        overwrite = False
        if split:
            existing = [path for path in outputs if path.exists()]
            if existing:
                answer = QMessageBox.question(
                    self, tr('覆蓋單頁檔案'),
                    tr('已有 {p0} 個同名單頁檔案，例如：\n{p1}\n\n是否覆蓋？', p0=len(existing), p1=existing[0]),
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
        self.statusBar().showMessage(tr('正在拆分單頁 PDF…') if split else tr('正在輸出 PDF…'))
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
        self.statusBar().showMessage(tr('輸出完成：{p0}', p0=destination))
        if self._export_split:
            outputs = split_output_paths(destination, count)
            message = tr('已拆分為 {p0} 個單頁 PDF：\n{p1}', p0=count, p1=outputs[0])
            if count > 1:
                message += f"\n…\n{outputs[-1]}"
        else:
            message = tr('已輸出 {p0} 頁至：\n{p1}', p0=count, p1=destination)
        QMessageBox.information(self, tr('輸出完成'), message)

    @Slot(int, str)
    def _export_failed(self, session: int, message: str) -> None:
        if session != self._export_id or self._closing:
            return
        self._set_export_running(False)
        self.statusBar().showMessage(tr('輸出失敗'))
        QMessageBox.critical(self, tr('輸出失敗'), localize_text(message))

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        if self._fullscreen_preview is not None:
            self._fullscreen_preview.close()
        for doc in self.documents.values():
            doc.render_timer.stop()
            doc.fit_timer.stop()
            doc.grid_host.finish_drag()
        self.render_service.close()
        self.thread_pool.clear()
        self.thread_pool.waitForDone()
        self.preview_temp.cleanup()
        self.language_controller.close()
        event.accept()


def load_app_icon() -> QIcon:
    return QIcon(str(files("repdf").joinpath("assets", "repdf.png")))


def configure_application(app: QApplication) -> None:
    app.setApplicationName("RePDF")
    app.setOrganizationName("repdf")
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
    window = MainWindow(render_backend)
    window.show()
    return app.exec()
