"""Small, flat toolbar icons drawn at device-independent coordinates."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication


def toolbar_icon(kind: str) -> QIcon:
    icon = QIcon()
    for mode, group in ((QIcon.Mode.Normal, QPalette.ColorGroup.Active),
                        (QIcon.Mode.Disabled, QPalette.ColorGroup.Disabled)):
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        painter.setPen(QPen(QApplication.palette().color(group, QPalette.ColorRole.ButtonText),
                            1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        if kind == "open":
            painter.drawPolyline(QPolygonF([QPointF(3, 19), QPointF(3, 5), QPointF(9, 5),
                                            QPointF(12, 8), QPointF(20, 8), QPointF(20, 10)]))
            painter.drawPolygon(QPolygonF([QPointF(3, 19), QPointF(7, 11), QPointF(22, 11),
                                           QPointF(18, 19)]))
        elif kind == "export":
            painter.drawPolyline(QPolygonF([QPointF(8, 16), QPointF(4, 16), QPointF(4, 3),
                                            QPointF(14, 3), QPointF(18, 7), QPointF(18, 10)]))
            painter.drawPolyline(QPolygonF([QPointF(14, 3), QPointF(14, 7), QPointF(18, 7)]))
            painter.drawLine(13, 11, 13, 20)
            painter.drawPolyline(QPolygonF([QPointF(9, 16), QPointF(13, 20), QPointF(17, 16)]))
            painter.drawPolyline(QPolygonF([QPointF(6, 20), QPointF(6, 22), QPointF(20, 22),
                                            QPointF(20, 20)]))
        elif kind == "split":
            painter.drawRoundedRect(QRectF(2, 2, 8, 13), 1, 1)
            painter.drawRoundedRect(QRectF(14, 9, 8, 13), 1, 1)
            painter.drawLine(6, 19, 12, 19)
            painter.drawPolyline(QPolygonF([QPointF(9, 16), QPointF(12, 19), QPointF(9, 22)]))
        elif kind in ("zoom_in", "zoom_out"):
            painter.drawEllipse(QRectF(3, 3, 13, 13))
            painter.drawLine(15, 15, 21, 21)
            painter.drawLine(6, 9, 13, 9)
            if kind == "zoom_in":
                painter.drawLine(9, 6, 9, 13)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon
