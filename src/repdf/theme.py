from __future__ import annotations

from importlib.resources import files

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication


class ThemeController(QObject):
    def __init__(self, app: QApplication, mode: str = "system", parent=None) -> None:
        super().__init__(parent or app)
        self.app = app
        self.mode = mode if mode in {"system", "light", "dark"} else "system"
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self.apply)
        self.apply()

    def set_mode(self, mode: str) -> None:
        if mode not in {"system", "light", "dark"}:
            raise ValueError(mode)
        self.mode = mode
        self.apply()

    @Slot()
    def apply(self, *_args: object) -> None:
        scheme = QGuiApplication.styleHints().colorScheme()
        dark = self.mode == "dark" or (self.mode == "system" and scheme == Qt.ColorScheme.Dark)
        palette = QPalette()
        colors = (
            {
                QPalette.ColorRole.Window: "#202124",
                QPalette.ColorRole.WindowText: "#f1f3f4",
                QPalette.ColorRole.Base: "#17181a",
                QPalette.ColorRole.AlternateBase: "#292a2d",
                QPalette.ColorRole.Text: "#f1f3f4",
                QPalette.ColorRole.Button: "#303134",
                QPalette.ColorRole.ButtonText: "#f1f3f4",
                QPalette.ColorRole.Highlight: "#8ab4f8",
                QPalette.ColorRole.HighlightedText: "#202124",
                QPalette.ColorRole.PlaceholderText: "#9aa0a6",
            }
            if dark
            else {
                QPalette.ColorRole.Window: "#f5f6f8",
                QPalette.ColorRole.WindowText: "#202124",
                QPalette.ColorRole.Base: "#ffffff",
                QPalette.ColorRole.AlternateBase: "#eef0f3",
                QPalette.ColorRole.Text: "#202124",
                QPalette.ColorRole.Button: "#ffffff",
                QPalette.ColorRole.ButtonText: "#202124",
                QPalette.ColorRole.Highlight: "#0b57d0",
                QPalette.ColorRole.HighlightedText: "#ffffff",
                QPalette.ColorRole.PlaceholderText: "#6f7378",
            }
        )
        for role, color in colors.items():
            palette.setColor(role, QColor(color))
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor("#777b80" if dark else "#9aa0a6"),
        )
        self.app.setPalette(palette)
        border = "#4a4d51" if dark else "#d5d8dc"
        card = "#292a2d" if dark else "#ffffff"
        slider_track = "#5f6368" if dark else "#c4c7c5"
        slider_fill = "#8ab4f8" if dark else "#0b57d0"
        slider_handle = "#aecbfa" if dark else "#0b57d0"
        hover = "#35383d" if dark else "#e7ebf0"
        pressed = "#41464e" if dark else "#d8e3f3"
        selected_tool = "#294366" if dark else "#d8e7ff"
        disabled = "#777b80" if dark else "#9aa0a6"
        check = files("repdf").joinpath("assets", "check.svg").as_posix()
        partial = files("repdf").joinpath("assets", "partial.svg").as_posix()
        self.app.setStyleSheet(
            f"""
            QFrame#pageCard {{ background: {card}; border: 1px solid {border};
                               border-radius: 8px; }}
            QFrame#pageCard QLabel, QFrame#pageCard QCheckBox {{ border: none; }}
            QToolBar {{ background: palette(window); border: none;
                        border-bottom: 1px solid {border}; padding: 4px; spacing: 4px; }}
            QToolBar::separator {{ background: {border}; width: 1px; margin: 5px 4px; }}
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{ background: transparent; color: palette(window-text);
                            border: none; border-bottom: 2px solid transparent;
                            padding: 5px 8px; margin-right: 2px; }}
            QTabBar::tab:selected {{ background: {card}; border-bottom-color: {slider_fill}; }}
            QTabBar::tab:!selected:hover {{ background: {hover}; }}
            QToolButton {{ background: transparent; border: 1px solid transparent;
                           border-radius: 4px; padding: 4px; color: palette(button-text); }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed {{ background: {pressed}; }}
            QToolButton#copyTextTool:checked {{ background: {selected_tool};
                                                border-color: {slider_fill}; }}
            QToolButton:focus {{ border-color: {slider_fill}; }}
            QToolButton:disabled {{ color: {disabled}; background: transparent; }}
            QPushButton {{ background: {card}; color: palette(button-text);
                           border: 1px solid {border}; border-radius: 5px;
                           min-height: 30px; padding: 2px 12px; }}
            QPushButton:hover {{ background: {hover}; border-color: {slider_fill}; }}
            QPushButton:pressed {{ background: {pressed}; }}
            QPushButton:focus {{ border-color: {slider_fill}; }}
            QPushButton:disabled {{ color: {disabled}; }}
            QCheckBox {{ spacing: 6px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px;
                                    border: 1px solid {border}; border-radius: 3px;
                                    background: {card}; }}
            QCheckBox::indicator:hover {{ border-color: {slider_fill}; }}
            QCheckBox::indicator:checked {{ background: #0b57d0; border-color: #0b57d0;
                                            image: url("{check}"); }}
            QCheckBox::indicator:indeterminate {{ background: #0b57d0; border-color: #0b57d0;
                                                  image: url("{partial}"); }}
            QCheckBox::indicator:disabled {{ background: {hover}; border-color: {border}; }}
            QScrollArea {{ border: 1px solid {border}; border-radius: 6px; }}
            QStatusBar {{ background: palette(window); border: none; }}
            QStatusBar::item {{ border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
            QScrollBar::handle {{ background: {slider_track}; border-radius: 3px;
                                 min-width: 24px; min-height: 24px; }}
            QScrollBar::handle:hover {{ background: {slider_fill}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
            QSlider::groove:horizontal {{ height: 2px; background: {slider_track};
                                          border-radius: 1px; }}
            QSlider::sub-page:horizontal {{ background: {slider_fill};
                                            border-radius: 1px; }}
            QSlider::add-page:horizontal {{ background: {slider_track};
                                            border-radius: 1px; }}
            QSlider::handle:horizontal {{ background: {slider_handle};
                                          border: none;
                                          border-radius: 5px; width: 10px;
                                          margin: -4px 0; }}
            """
        )
