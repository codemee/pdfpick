from __future__ import annotations

from repdf.strings import tr

from PySide6.QtCore import QEasingCurve, QMimeData, QPoint, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QImage, QMouseEvent, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class PageGrid(QWidget):
    """Keep drop hit areas stable while cards animate into preview slots."""

    insertion_requested = Signal(int, int)
    drag_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.cards = []
        self.drag_source = None
        self._slots = []
        self._animations = {}
        self._insertion = None
        self._gap = QFrame(self)
        self._gap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._gap.setStyleSheet("border: 2px dashed palette(highlight); border-radius: 8px; background: transparent;")
        self._gap.hide()

    def begin_drag(self, source) -> None:
        self.layout().activate()
        self.cards = [self.layout().itemAt(i).widget() for i in range(self.layout().count())]
        self._slots = [card.geometry() for card in self.cards]
        self.drag_source = source
        self._insertion = self.cards.index(source)
        self.layout().setEnabled(False)
        source.hide()
        self._show_gap(self._insertion)

    def finish_drag(self) -> None:
        if self.drag_source is None:
            return
        self._stop_animations()
        self._gap.hide()
        self.drag_source.show()
        self.drag_source = None
        self._insertion = None
        self.layout().setEnabled(True)
        self.cards = []
        self._slots = []
        self.drag_finished.emit()

    def _stop_animations(self) -> None:
        for animation in self._animations.values():
            animation.stop()
            animation.deleteLater()
        self._animations.clear()

    def _show_gap(self, insertion: int) -> None:
        self._gap.setGeometry(self._slots[insertion])
        self._gap.show()
        self._gap.lower()

    def preview_at(self, position: QPoint) -> None:
        if self.drag_source is None:
            return
        # Use original slots, never the moving widgets, to avoid flickering targets.
        slot = min(range(len(self._slots)), key=lambda i:
                   (self._slots[i].center() - position).manhattanLength())
        boundary = slot + int(position.x() > self._slots[slot].center().x())
        source_position = self.cards.index(self.drag_source)
        insertion = boundary - int(boundary > source_position)
        self._preview_insertion(insertion)

    def _preview_insertion(self, insertion: int) -> None:
        if insertion == self._insertion:
            self._show_gap(insertion)
            return
        self._insertion = insertion
        self._stop_animations()
        order = [card for card in self.cards if card is not self.drag_source]
        order.insert(insertion, self.drag_source)
        for index, card in enumerate(order):
            if card is self.drag_source:
                continue
            destination = self._slots[index].topLeft()
            if card.pos() == destination:
                continue
            animation = QPropertyAnimation(card, b"pos", self)
            animation.setDuration(180)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            animation.setStartValue(card.pos())
            animation.setEndValue(destination)
            self._animations[card] = animation
            animation.start()
        self._show_gap(insertion)

    def _accepts(self, event) -> bool:
        return (self.drag_source is not None and event.source() is self.drag_source
                and event.mimeData().hasFormat(PageCard.DRAG_MIME_TYPE))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accepts(event):
            self.preview_at(event.position().toPoint())
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        if self.drag_source is not None:
            self._preview_insertion(self.cards.index(self.drag_source))
            self._gap.hide()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        if not self._accepts(event):
            event.ignore()
            return
        self.preview_at(event.position().toPoint())
        self.insertion_requested.emit(self.drag_source.page_index, self._insertion)
        event.acceptProposedAction()


class DragLabel(QLabel):
    drag_requested = Signal()
    pressed = Signal()

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self._press_position = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tr('拖曳到另一頁可調整順序'))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
            self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._press_position is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.position().toPoint() - self._press_position).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._press_position = None
            self.drag_requested.emit()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_position = None
        super().mouseReleaseEvent(event)


class PagePreviewLabel(DragLabel):
    text_selected = Signal(QPoint, QPoint)
    selection_preview = Signal(QPoint, QPoint)

    def __init__(self, text: str, *, draggable: bool = True) -> None:
        super().__init__(text)
        self.draggable = draggable
        self.text_mode = False
        self.region_mode = False
        self._selection_start = None
        self._selection_end = None
        self._selecting = False
        self._highlight_rects = []
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self._preview_selection)
        if not draggable:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_text_mode(self, enabled: bool, *, region: bool = False) -> None:
        self.text_mode = enabled
        self.region_mode = enabled and region
        self._selection_start = None
        self._selection_end = None
        self._selecting = False
        self._highlight_rects = []
        self._preview_timer.stop()
        self._press_position = None
        self.setCursor(Qt.CursorShape.CrossCursor if self.region_mode else Qt.CursorShape.IBeamCursor if enabled else
                       Qt.CursorShape.OpenHandCursor if self.draggable else Qt.CursorShape.ArrowCursor)
        self.setToolTip(tr('框選區域並以 OCR 複製文字') if self.region_mode else tr('拖曳選取文字並複製到剪貼簿') if enabled else
                        tr('拖曳到另一頁可調整順序') if self.draggable else '')
        self.update()

    def set_text_highlights(self, rects) -> None:
        if not self._selecting:
            self._selection_start = None
            self._selection_end = None
        self._highlight_rects = rects
        self.update()

    def _preview_selection(self) -> None:
        if not self.region_mode and self._selecting and self._selection_start is not None and self._selection_end is not None:
            self.selection_preview.emit(self._selection_start, self._selection_end)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.text_mode:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit()
            self._selection_start = event.position().toPoint()
            self._selection_end = self._selection_start
            self._selecting = True
            self._highlight_rects = []
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.text_mode:
            if self.draggable:
                super().mouseMoveEvent(event)
            return
        if self._selecting and event.buttons() & Qt.MouseButton.LeftButton:
            self._selection_end = event.position().toPoint()
            if not self.region_mode and not self._preview_timer.isActive():
                self._preview_timer.start()
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self.text_mode:
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._selecting:
            self._preview_timer.stop()
            self._selection_end = event.position().toPoint()
            if (self._selection_end - self._selection_start).manhattanLength() >= QApplication.startDragDistance():
                self.text_selected.emit(self._selection_start, self._selection_end)
            self._selecting = False
            self.update()
            event.accept()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.text_mode:
            return
        painter = QPainter(self)
        highlight = self.palette().highlight().color()
        highlight.setAlpha(90)
        if self._highlight_rects:
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            for x0, y0, x1, y1 in self._highlight_rects:
                path.addRect(QRectF(x0 * self.width(), y0 * self.height(),
                                    (x1 - x0) * self.width(), (y1 - y0) * self.height()))
            painter.fillPath(path, highlight)
        elif self._selection_start is not None and self._selection_end is not None:
            rectangle = QRect(self._selection_start, self._selection_end).normalized().intersected(self.rect())
            painter.fillRect(rectangle, highlight)
            if self.region_mode:
                painter.setPen(self.palette().highlight().color())
                painter.drawRect(rectangle.adjusted(0, 0, -1, -1))
        painter.end()


class PageCard(QFrame):
    focused = Signal(int)
    selection_changed = Signal(int, bool)
    reorder_requested = Signal(int, int)
    text_selected = Signal(int, QPoint, QPoint)
    selection_preview = Signal(int, QPoint, QPoint)
    DRAG_MIME_TYPE = "application/x-repdf-page"

    def __init__(self, page_index: int, target_width: int) -> None:
        super().__init__()
        self.page_index = page_index
        self.target_width = target_width
        self.text_copy_mode = False
        self.setObjectName("pageCard")
        self.setFixedWidth(target_width + 24)
        self.setAcceptDrops(False)

        self.checkbox = QCheckBox(tr('第 {p0} 頁', p0=page_index + 1))
        self.checkbox.clicked.connect(
            lambda checked: self.selection_changed.emit(self.page_index, checked)
        )
        self.drag_handle = DragLabel(tr('☰ 拖曳排序'))
        self.drag_handle.drag_requested.connect(self._start_drag)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.checkbox)
        header.addStretch()
        header.addWidget(self.drag_handle)

        self.preview = PagePreviewLabel(tr('載入中…'))
        self.preview.pressed.connect(lambda: self.focused.emit(self.page_index))
        self.drag_handle.pressed.connect(lambda: self.focused.emit(self.page_index))
        self.checkbox.clicked.connect(lambda: self.focused.emit(self.page_index))
        self.preview.drag_requested.connect(self._start_drag)
        self.preview.text_selected.connect(
            lambda start, end: self.text_selected.emit(self.page_index, start, end))
        self.preview.selection_preview.connect(
            lambda start, end: self.selection_preview.emit(self.page_index, start, end))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(max(80, int(target_width * 1.3)))
        self.preview.setFixedWidth(target_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 11)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _start_drag(self) -> None:
        if self.text_copy_mode or getattr(self.window(), "_export_running", False):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(self.DRAG_MIME_TYPE, str(self.page_index).encode("ascii"))
        drag.setMimeData(mime)
        pixmap = self.drag_pixmap()
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(pixmap.width() // 2, min(24, pixmap.height() // 2)))
        cursor = QPixmap(1, 1)
        cursor.fill(Qt.GlobalColor.transparent)
        drag.setDragCursor(cursor, Qt.DropAction.MoveAction)
        host = self.parentWidget()
        if isinstance(host, PageGrid):
            host.begin_drag(self)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            if isinstance(host, PageGrid):
                host.finish_drag()
            drag.deleteLater()

    def drag_pixmap(self) -> QPixmap:
        # Include the page number, and use a bounded size even at 200% zoom.
        return self.grab().scaled(180, 240, Qt.AspectRatioMode.KeepAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)

    def _drag_source(self, event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> PageCard | None:
        source = event.source()
        if (
            isinstance(source, PageCard)
            and source is not self
            and source.window() is self.window()
            and event.mimeData().hasFormat(self.DRAG_MIME_TYPE)
        ):
            return source
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._drag_source(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._drag_source(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        source = self._drag_source(event)
        if source is None:
            event.ignore()
            return
        self.reorder_requested.emit(source.page_index, self.page_index)
        event.acceptProposedAction()

    def set_selected(self, selected: bool) -> None:
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(selected)
        self.checkbox.blockSignals(False)

    def set_text_copy_mode(self, enabled: bool, *, region: bool = False) -> None:
        self.text_copy_mode = enabled
        self.preview.set_text_mode(enabled, region=region)
        self.drag_handle.setCursor(Qt.CursorShape.ArrowCursor if enabled else Qt.CursorShape.OpenHandCursor)
        self.drag_handle.setToolTip(tr('文字複製模式中無法拖放頁面') if enabled else
                                    tr('拖曳到另一頁可調整順序'))

    def set_target_width(self, width: int) -> None:
        self.target_width = width
        self.setFixedWidth(width + 24)
        self.preview.setFixedWidth(width)
        self.preview.setMinimumHeight(max(80, int(width * 1.3)))
        self.preview.setText(tr('載入中…'))
        self.preview.setPixmap(QPixmap())

    def set_image(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        self.target_width = pixmap.width()
        self.setFixedWidth(pixmap.width() + 24)
        self.preview.setMinimumHeight(0)
        self.preview.setFixedSize(pixmap.size())
        self.preview.setPixmap(pixmap)

    def set_render_error(self) -> None:
        self.preview.setMinimumHeight(max(80, int(self.target_width * 1.3)))
        self.preview.setText(tr('無法產生預覽'))
