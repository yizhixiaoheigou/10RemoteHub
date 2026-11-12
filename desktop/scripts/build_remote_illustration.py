#!/usr/bin/env python3
"""Draw the remote illustration shipped with the App.

The original bundle used a photo of the physical remote, whose redistribution
rights were never established. This script draws a neutral illustration with
exactly the same canvas (793 x 1983) and the same button rectangles as
`remotehub/photo_template.py`, so the mapping hotspots keep their positions.

Run: .venv-mac/bin/python scripts/build_remote_illustration.py
"""
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'remotehub/assets/remote-tv.png'
W, H = 793, 1983
BODY = QRectF(128, 40, 537, 1868)
TEXT = QColor('#eceff1')
FONT = 'PingFang SC'


def round_rect(painter, rect, radius, fill, border=None, border_width=1.5):
    painter.setPen(QPen(QColor(border), border_width) if border else Qt.NoPen)
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(rect, radius, radius)


def button(painter, rect, radius=None):
    """Raised dark key with a soft top highlight."""
    radius = rect.height() / 2 if radius is None else radius
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, QColor('#2f3034'))
    grad.setColorAt(0.55, QColor('#26272a'))
    grad.setColorAt(1.0, QColor('#1e1f22'))
    painter.setPen(QPen(QColor('#0c0d0e'), 2.0))
    painter.setBrush(grad)
    painter.drawRoundedRect(rect, radius, radius)
    painter.setPen(QPen(QColor(255, 255, 255, 26), 1.2))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 1, radius - 1)


def label(painter, rect, text, size, color=TEXT, weight=QFont.Weight.DemiBold):
    font = QFont(FONT, 1)
    font.setPixelSize(int(size))
    font.setWeight(weight)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(rect, Qt.AlignCenter, text)


def glyph(painter, center, radius, color):
    """Microphone mark used on the voice key."""
    pen = QPen(color, radius * 0.16, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    body = QRectF(center.x() - radius * 0.21, center.y() - radius * 0.66,
                  radius * 0.42, radius * 1.00)
    painter.drawRoundedRect(body, body.width() / 2, body.width() / 2)
    painter.drawArc(QRectF(center.x() - radius * 0.52, center.y() - radius * 0.34,
                           radius * 1.04, radius * 0.94), 200 * 16, 140 * 16)
    painter.drawLine(QPointF(center.x(), center.y() + radius * 0.56),
                     QPointF(center.x(), center.y() + radius * 0.86))


def power_glyph(painter, center, radius):
    pen = QPen(QColor('#e05252'), radius * 0.20, Qt.SolidLine, Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(center.x() - radius * 0.62, center.y() - radius * 0.62,
                           radius * 1.24, radius * 1.24), 130 * 16, 280 * 16)
    painter.drawLine(QPointF(center.x(), center.y() - radius * 0.92),
                     QPointF(center.x(), center.y() - radius * 0.10))


def directional(painter, center, size, color):
    path = QPainterPath()
    path.moveTo(center.x(), center.y() - size)
    path.lineTo(center.x() + size * 0.9, center.y() + size * 0.55)
    path.lineTo(center.x() - size * 0.9, center.y() + size * 0.55)
    path.closeSubpath()
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


def draw():
    QGuiApplication.instance() or QGuiApplication([])
    image = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    # Body and subtle face shading.
    body = QPainterPath()
    body.addRoundedRect(BODY, 96, 96)
    grad = QLinearGradient(BODY.topLeft(), BODY.bottomLeft())
    grad.setColorAt(0.0, QColor('#212226'))
    grad.setColorAt(0.5, QColor('#191a1d'))
    grad.setColorAt(1.0, QColor('#121315'))
    painter.setPen(QPen(QColor('#33353a'), 2.0))
    painter.setBrush(grad)
    painter.drawPath(body)
    shine = QRadialGradient(QPointF(300, 260), 620)
    shine.setColorAt(0.0, QColor(255, 255, 255, 14))
    shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.NoPen)
    painter.setBrush(shine)
    painter.drawPath(body)

    # Power and TV.
    power = QRectF(194, 186, 108, 104)
    button(painter, power)
    power_glyph(painter, power.center(), 34)
    tv = QRectF(493, 186, 108, 104)
    button(painter, tv)
    label(painter, tv, 'TV', 34)

    # Settings and mute pills.
    settings = QRectF(191, 315, 114, 77)
    button(painter, settings, 38)
    label(painter, settings, '设置', 26)
    mute = QRectF(489, 315, 114, 77)
    button(painter, mute, 38)
    label(painter, mute, '静音', 26)

    # Directional ring with a centre OK key.
    ring = QRectF(236, 395, 322, 322)
    painter.setPen(QPen(QColor('#0c0d0e'), 2.0))
    painter.setBrush(QColor('#1c1d20'))
    painter.drawEllipse(ring)
    painter.setPen(QPen(QColor(255, 255, 255, 22), 1.2))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(ring.adjusted(3, 3, -3, -3))
    center = ring.center()
    directional(painter, QPointF(center.x(), center.y() - 118), 26, TEXT)
    directional(painter, QPointF(center.x(), center.y() + 118), -26, TEXT)
    painter.save()
    painter.translate(center)
    painter.rotate(-90)
    directional(painter, QPointF(0, -118), 26, TEXT)
    painter.rotate(180)
    directional(painter, QPointF(0, -118), 26, TEXT)
    painter.restore()
    ok = QRectF(center.x() - 86, center.y() - 86, 172, 172)
    button(painter, ok)
    label(painter, ok, '确定', 34)

    # Menu, voice, back.
    menu = QRectF(193, 745, 112, 77)
    button(painter, menu, 38)
    label(painter, menu, '菜单', 26)
    back = QRectF(490, 745, 112, 77)
    button(painter, back, 38)
    label(painter, back, '返回', 26)
    voice = QRectF(328, 763, 138, 136)
    button(painter, voice, 68)
    glyph(painter, voice.center(), 40, QColor('#3fb2f0'))

    # Volume and channel rockers.
    for x in (198, 499):
        rocker = QRectF(x, 903, 101, 236)
        button(painter, rocker, 50)
    label(painter, QRectF(198, 910, 101, 60), '+', 40, weight=QFont.Weight.Medium)
    label(painter, QRectF(198, 1030, 101, 50), '音量', 23, weight=QFont.Weight.Medium)
    label(painter, QRectF(198, 1082, 101, 52), '−', 40, weight=QFont.Weight.Medium)
    label(painter, QRectF(499, 910, 101, 60), '+', 40, weight=QFont.Weight.Medium)
    label(painter, QRectF(499, 1030, 101, 50), '频道', 23, weight=QFont.Weight.Medium)
    label(painter, QRectF(499, 1082, 101, 52), '−', 40, weight=QFont.Weight.Medium)

    # Home and M.
    home = QRectF(348, 912, 99, 100)
    button(painter, home)
    label(painter, home, '主页', 25)
    m = QRectF(348, 1029, 99, 99)
    button(painter, m)
    label(painter, m, 'M', 34)

    # Number pad, three columns by four rows.
    for row, keys in enumerate(('123', '456', '789', '#0*')):
        for column, key in enumerate(keys):
            rect = QRectF((198, 348, 498)[column], 1160 + row * 116, 102, 102)
            button(painter, rect)
            label(painter, rect, key, 40, weight=QFont.Weight.Medium)

    painter.end()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(OUT), 'PNG'):
        raise SystemExit('无法写入 ' + str(OUT))
    print('wrote', OUT, image.width(), 'x', image.height())


if __name__ == '__main__':
    draw()
