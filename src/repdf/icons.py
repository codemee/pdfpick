"""Small, flat toolbar icons drawn at device-independent coordinates."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF
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
        if kind in ("language_zh", "language_en"):
            font = QFont(QApplication.font())
            font.setPixelSize(16)
            painter.setFont(font)
            painter.drawText(QRectF(1, 1, 22, 22), Qt.AlignmentFlag.AlignCenter,
                             "中" if kind == "language_zh" else "En")
        elif kind == "language_system":
            painter.drawEllipse(QRectF(3, 3, 18, 18))
            painter.drawEllipse(QRectF(8, 3, 8, 18))
            painter.drawLine(3, 12, 21, 12)
        elif kind == "theme_system":
            circle = QPainterPath()
            circle.addEllipse(QRectF(3, 3, 18, 18))
            painter.fillPath(circle, Qt.GlobalColor.white)
            painter.save()
            painter.setClipPath(circle)
            painter.fillRect(QRectF(12, 3, 9, 18), Qt.GlobalColor.black)
            painter.restore()
            painter.drawPath(circle)
        elif kind == "theme_light":
            painter.drawEllipse(QRectF(7, 7, 10, 10))
            for x1, y1, x2, y2 in ((12, 2, 12, 4), (12, 20, 12, 22), (2, 12, 4, 12),
                                    (20, 12, 22, 12), (5, 5, 6, 6), (18, 18, 19, 19),
                                    (5, 19, 6, 18), (18, 6, 19, 5)):
                painter.drawLine(x1, y1, x2, y2)
        elif kind == "theme_dark":
            path = QPainterPath(QPointF(11, 3))
            path.cubicTo(1, 4, 1, 19, 12, 21)
            path.cubicTo(17, 22, 21, 18, 21, 14)
            path.cubicTo(10, 18, 6, 9, 11, 3)
            painter.drawPath(path)
        elif kind == "fit":
            for points in (((3, 8), (3, 3), (8, 3)), ((16, 3), (21, 3), (21, 8)),
                           ((21, 16), (21, 21), (16, 21)), ((8, 21), (3, 21), (3, 16))):
                painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
            painter.drawRect(QRectF(8, 6, 8, 12))
        elif kind == "copy_text":
            painter.drawLine(3, 4, 18, 4)
            painter.drawLine(3, 8, 16, 8)
            painter.drawLine(3, 12, 13, 12)
            painter.drawLine(3, 16, 10, 16)
            painter.drawLine(17, 11, 17, 21)
            painter.drawLine(14, 11, 20, 11)
            painter.drawLine(14, 21, 20, 21)
        elif kind in ("fullscreen", "fullscreen_spread", "fullscreen_cover"):
            if kind == "fullscreen":
                painter.drawRect(QRectF(5, 2, 14, 20))
                painter.drawLine(8, 11, 16, 11)
                painter.drawLine(8, 15, 16, 15)
            elif kind == "fullscreen_spread":
                painter.drawRect(QRectF(3, 4, 18, 17))
                painter.drawLine(12, 4, 12, 21)
                painter.drawLine(5, 12, 9, 12)
                painter.drawLine(15, 12, 19, 12)
            else:
                painter.drawRect(QRectF(1, 2, 10, 19))
                painter.drawLine(4, 11, 8, 11)
                # A separate cover beside two pages sharing their center edge.
                painter.drawRect(QRectF(13, 8, 10, 13))
                painter.drawLine(18, 8, 18, 21)
        elif kind == "open":
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
