from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QWidget

from repdf.strings import tr
from repdf.widgets import PagePreviewLabel


class FullscreenPreview(QWidget):
    """Display ordered pages at a common scale and share document selection."""

    HEADER_HEIGHT = 30
    PAGE_GAP = 12

    def __init__(self, owner, document, page_index, mode="single"):
        super().__init__(owner, Qt.WindowType.Window)
        self.owner = owner
        self.document = document
        self.mode = mode
        order = document.page_order
        if mode == "single":
            self.groups = [[page] for page in order]
        elif mode == "spread":
            self.groups = [order[i:i + 2] for i in range(0, len(order), 2)]
        elif mode == "cover":
            self.groups = [order[:1]] + [order[i:i + 2] for i in range(1, len(order), 2)]
        else:
            raise ValueError(f"Unknown preview mode: {mode}")
        self.render_generation = -1
        self.images = {}
        self.labels = {}
        self.checkboxes = {}
        self.closed = False
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setStyleSheet("background: palette(window);")
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.request_render)
        QApplication.instance().installEventFilter(self)
        self.show_page(page_index)

    @property
    def image(self):
        return self.images.get(self.page_index, QImage())

    @property
    def label(self):
        return self.labels[self.page_index]

    def show_page(self, page_index):
        self.render_generation = -1
        self.owner.render_service.cancel_pending(-self.document.document_id)
        self.group_index = next(i for i, group in enumerate(self.groups) if page_index in group)
        self.visible_pages = self.groups[self.group_index]
        self.page_index = self.visible_pages[0]
        for widget in list(self.labels.values()) + list(self.checkboxes.values()):
            widget.hide()
            widget.deleteLater()
        self.images = {}
        self.labels = {}
        self.checkboxes = {}
        for index in self.visible_pages:
            self.images[index] = self.document.page_cards[index].preview.pixmap().toImage()
            label = PagePreviewLabel('', draggable=False)
            label.setParent(self)
            label.set_text_mode(self.owner.copy_text_action.isChecked())
            label.text_selected.connect(
                lambda start, end, page=index, preview=label:
                self.owner._copy_text_selection(self.document, page, preview, start, end))
            label.selection_preview.connect(
                lambda start, end, page=index, preview=label:
                self.owner._copy_text_selection(self.document, page, preview, start, end, copy=False))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if self.images[index].isNull():
                label.setText(tr("正在產生頁面預覽…"))
            label.show()
            self.labels[index] = label
            checkbox = QCheckBox(tr("第 {p0} 頁", p0=index + 1), self)
            checkbox.setChecked(index in self.document.selected_pages)
            checkbox.setEnabled(not self.owner._export_running)
            checkbox.toggled.connect(lambda checked, page=index: self._select_page(page, checked))
            checkbox.show()
            self.checkboxes[index] = checkbox
        self.update_image()
        self.timer.start()

    def _select_page(self, index, checked):
        self.document.page_cards[index].set_selected(checked)
        self.document._page_selection_changed(index, checked)

    def _page_sizes(self):
        result = {}
        for index in self.visible_pages:
            size = self.document.page_sizes.get(index)
            if size is None:
                image = self.images[index]
                size = (image.width(), image.height()) if not image.isNull() else (595, 842)
            result[index] = size
        return result

    def _fit_scale(self, sizes):
        width = sum(size[0] for size in sizes.values())
        height = max(size[1] for size in sizes.values())
        gap = self.PAGE_GAP * (len(sizes) - 1)
        return max(.001, min(max(1, self.width() - gap) / width,
                             max(1, self.height() - self.HEADER_HEIGHT) / height))

    def request_render(self):
        if self.closed:
            return
        sizes = self._page_sizes()
        scale = self._fit_scale(sizes) * self.devicePixelRatioF()
        area = sum(width * height for width, height in sizes.values())
        scale = min(scale, (30_000_000 / area) ** .5)
        self.owner._next_generation += 1
        self.render_generation = self.owner._next_generation
        self.owner.render_service.request(self.document.source_path, scale,
                                         Path(self.owner.preview_temp.name), self.render_generation,
                                         document_id=-self.document.document_id, pages=self.visible_pages)
        self.owner.render_service.prioritize(-self.document.document_id)

    def accept_render(self, payload):
        if payload.get("type") == "page":
            index = int(payload["page"])
            path = Path(payload["path"])
            image = QImage(str(path)).copy()
            path.unlink(missing_ok=True)
            if index not in self.visible_pages:
                return
            self.images[index] = image
            unknown_size = index not in self.document.page_sizes
            self.document.page_sizes[index] = (
                float(payload["width_points"]), float(payload["height_points"]))
            self.update_image()
            if unknown_size:
                self.timer.start()
        elif payload.get("type") == "error":
            for index, image in self.images.items():
                if image.isNull():
                    self.labels[index].setText(tr("無法產生預覽"))

    def update_image(self):
        sizes = self._page_sizes()
        scale = self._fit_scale(sizes)
        spread_width = sum(width * scale for width, _ in sizes.values()) + self.PAGE_GAP * (len(sizes) - 1)
        spread_height = max(height * scale for _, height in sizes.values())
        x = (self.width() - spread_width) / 2
        y = self.HEADER_HEIGHT + (self.height() - self.HEADER_HEIGHT - spread_height) / 2
        ratio = self.devicePixelRatioF()
        for index, (width, height) in sizes.items():
            label = self.labels[index]
            label.setGeometry(round(x), round(y), max(1, round(width * scale)), max(1, round(height * scale)))
            checkbox = self.checkboxes[index]
            checkbox.adjustSize()
            checkbox.move(round(x) + 6, round(y) - self.HEADER_HEIGHT + 4)
            image = self.images[index]
            if not image.isNull():
                pixmap = QPixmap.fromImage(image).scaled(
                    label.size() * ratio, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                pixmap.setDevicePixelRatio(ratio)
                label.setPixmap(pixmap)
            x += width * scale + self.PAGE_GAP

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "timer"):
            self.update_image()
            self.timer.start()

    def eventFilter(self, watched, event):
        if (not self.closed and isinstance(watched, QWidget) and watched.window() is self
                and event.type() == QEvent.Type.KeyPress and not event.modifiers()):
            return self._handle_key(event.key())
        return super().eventFilter(watched, event)

    def _handle_key(self, key):
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_F11):
            self.close()
            return True
        previous = (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp)
        following = (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown)
        if key in previous + following:
            position = self.group_index + (-1 if key in previous else 1)
            if 0 <= position < len(self.groups):
                self.show_page(self.groups[position][0])
            return True
        return False

    def closeEvent(self, event):
        self.closed = True
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        self.owner.render_service.cancel_pending(-self.document.document_id)
        self.owner._fullscreen_preview = None
        self.owner.activateWindow()
        self.deleteLater()
        event.accept()
