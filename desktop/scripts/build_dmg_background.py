#!/usr/bin/env python3
"""Draw the DMG window background (1x and 2x) used by scripts/build_dmg.py."""
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'assets/dmg'
W, H = 620, 400


def draw(scale):
    image = QImage(W * scale, H * scale, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.scale(scale, scale)

    base = QLinearGradient(QPointF(0, 0), QPointF(0, H))
    base.setColorAt(0.0, QColor('#fbfcfd'))
    base.setColorAt(1.0, QColor('#e9edf3'))
    painter.fillRect(QRectF(0, 0, W, H), base)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(31, 41, 55, 10))
    for x in range(0, W + 1, 24):
        for y in range(0, H + 1, 24):
            painter.drawEllipse(QPointF(x, y), 1.1, 1.1)

    title = QFont('PingFang SC', 1)
    title.setPixelSize(24)
    title.setWeight(QFont.Weight.DemiBold)
    painter.setFont(title)
    painter.setPen(QColor('#111827'))
    painter.drawText(QRectF(0, 46, W, 34), Qt.AlignCenter, '10RemoteHub')

    sub = QFont('PingFang SC', 1)
    sub.setPixelSize(13)
    painter.setFont(sub)
    painter.setPen(QColor('#6b7280'))
    painter.drawText(QRectF(0, 80, W, 22), Qt.AlignCenter, '遥控器、按键与语音，一处配置')

    # Arrow between the App and the Applications shortcut.
    arrow = QPainterPath()
    shaft = QRectF(230, 181, 108, 18)
    arrow.addRoundedRect(shaft, 9, 9)
    head = QPainterPath()
    head.moveTo(336, 166)
    head.lineTo(380, 190)
    head.lineTo(336, 214)
    head.closeSubpath()
    arrow.addPath(head)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#c7ced8'))
    painter.drawPath(arrow)
    painter.setBrush(QColor('#dbe1e9'))
    painter.drawRoundedRect(QRectF(230, 183, 108, 6), 3, 3)

    caption = QFont('PingFang SC', 1)
    caption.setPixelSize(13)
    painter.setFont(caption)
    painter.setPen(QColor('#9aa3af'))
    painter.drawText(QRectF(0, 344, W, 24), Qt.AlignCenter, '把左边的 App 拖进「应用程序」')
    painter.end()
    return image


def main():
    QGuiApplication.instance() or QGuiApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    for scale, name in ((1, 'background.png'), (2, 'background@2x.png')):
        if not draw(scale).save(str(OUT / name), 'PNG'):
            raise SystemExit('无法写入 ' + name)
        print('wrote', OUT / name)


if __name__ == '__main__':
    main()
