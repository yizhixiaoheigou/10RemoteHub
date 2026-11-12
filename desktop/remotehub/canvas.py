"""Remote photo with one leader line and label per key.

Routing: each key exits its hotspot horizontally to an elbow just outside the
photo, then runs diagonally to its label. Labels on each side are ordered by
the key's (offset) row, so no two leaders cross; keys sharing a row get a
small vertical offset so their horizontal runs never coincide.

Public surface used by ui.mapping and key_survey.SurveyCanvas:
signals selected/activated/region, set_profile, set_edit, image_rect,
hotspot_rect, layout_callouts, callouts, lines, anchors, hit_test.
"""
import base64
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import QPixmap, QPainter, QPen, QPainterPath, QPainterPathStroker, QFont, QFontMetrics
from PySide6.QtWidgets import QWidget, QPushButton
from .presentation import action_text  # re-exported for older imports
from .theme import qcolor, repolish

LABEL_H = 24
LABEL_GAP = 4
LABEL_MAX_W = 190
ELBOW = 18        # photo edge -> elbow
COLUMN = 44       # photo edge -> label column
ROW_TOL = 0.02    # keys within 2 % of image height share a row
ROW_OFFSET = 4.0  # px between horizontal runs that share a row
CENTRE_BAND = 0.08  # |centre x − 0.5| below this: key may go to either side
NEAR_ROWS = 0.06    # "near its row" for side balancing, in image heights


def callout_text(button):
    if not button.configurable:
        return button.name + " · 不能设置", "blocked"
    if all(action.kind == "none" for action in (button.action, button.double_action, button.long_action)):
        return button.name, "empty"
    if button.double_action.kind == button.long_action.kind == "none":
        return button.name + "  " + action_text(button.action), "assigned"
    parts = []
    if button.action.kind != "none":
        parts.append(action_text(button.action))
    if button.double_action.kind != "none":
        parts.append("双击 " + action_text(button.double_action))
    if button.long_action.kind != "none":
        parts.append("长按 " + action_text(button.long_action))
    return button.name + "  " + " / ".join(parts), "assigned"


class RemoteCanvas(QWidget):
    selected = Signal(str)
    activated = Signal(str)
    region = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = None
        self.selection = ""
        self.hover = ""
        self.pixmap = QPixmap()
        self._image = None
        self.edit = False
        self.origin = None
        self.drag_end = None
        self.callouts = {}
        self.lines = {}
        self.anchors = {}
        # Leave room for the sidebar, inspector, margins and scrollbars at
        # the supported 1200 px minimum window width.
        self.setMinimumSize(576, 520)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("遥控器按键图；Tab 聚焦按键标签，方向键切换按键，Enter 编辑动作")

    # -- model -----------------------------------------------------------

    def set_profile(self, profile, selection=""):
        self.profile = profile
        self.selection = selection
        if profile.image != self._image:
            self._image = profile.image
            self.pixmap = QPixmap()
            if profile.image:
                self.pixmap.loadFromData(base64.b64decode(profile.image))
        ids = {b.id for b in profile.buttons}
        for ident in set(self.callouts) - ids:
            stale = self.callouts.pop(ident)
            stale.hide()
            stale.deleteLater()
        for b in profile.buttons:
            if b.id not in self.callouts:
                label = QPushButton(self)
                label.setProperty("role", "callout")
                label.setCheckable(True)
                label.setCursor(Qt.CursorShape.PointingHandCursor)
                label.clicked.connect(lambda checked=False, ident=b.id: self._label_clicked(ident))
                self.callouts[b.id] = label
            label = self.callouts[b.id]
            text, state = callout_text(b)
            label.setEnabled(b.configurable)
            label.setToolTip(text + ("\n点击选择此键，在右侧分配动作" if b.configurable else "\n此键不能设置"))
            label.setAccessibleName(text)
            label.setChecked(b.id == selection)
            if label.property("state") != state:
                label.setProperty("state", state)
                repolish(label)
        ordered = [self.callouts[b.id] for b in profile.buttons]
        for left, right in zip(ordered, ordered[1:]):
            QWidget.setTabOrder(left, right)
        self.layout_callouts()
        self.update()

    def _label_clicked(self, ident):
        # A checkable label toggles itself; the controller decides selection.
        self.callouts[ident].setChecked(ident == self.selection)
        self.selected.emit(ident)

    def set_edit(self, on):
        self.edit = on
        self.origin = None
        self.drag_end = None
        self.update()

    def set_hover(self, ident):
        if ident != self.hover:
            self.hover = ident
            self.update()

    def label_text(self, button):
        """Override point for canvases that show other per-key state."""
        return callout_text(button)[0]

    # -- geometry ----------------------------------------------------------

    def image_rect(self):
        ratio = self.pixmap.width() / self.pixmap.height() if not self.pixmap.isNull() else 0.4
        margin_x = min(300, max(210, self.width() * 0.3))
        avail_w = max(80, self.width() - margin_x * 2)
        avail_h = max(80, self.height() - 32)
        width = min(avail_w, avail_h * ratio)
        height = width / ratio
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def hotspot_rect(self, button):
        area = self.image_rect()
        x, y, w, h = button.rect
        return QRectF(area.x() + x * area.width(), area.y() + y * area.height(),
                      w * area.width(), h * area.height())

    def _rows(self, buttons, side, area):
        """Anchor points with same-row keys nudged apart; returns [(button, anchor)] top→bottom."""
        items = []
        for b in buttons:
            rect = self.hotspot_rect(b)
            items.append((b, rect, rect.center().y()))
        items.sort(key=lambda item: item[2])
        groups, tolerance = [], ROW_TOL * area.height()
        for item in items:
            if groups and abs(item[2] - groups[-1][0][2]) <= tolerance:
                groups[-1].append(item)
            else:
                groups.append([item])
        result = []
        for group in groups:
            # Outer keys (nearest the label column) take the upper offset so
            # their short horizontal run sits above the inner keys' longer one.
            group.sort(key=lambda item: item[1].left() if side == 0 else -item[1].right())
            centre = (len(group) - 1) / 2
            for rank, (b, rect, y) in enumerate(group):
                y += (rank - centre) * ROW_OFFSET
                x = rect.left() if side == 0 else rect.right()
                result.append((b, QPointF(x, y)))
        return result

    @staticmethod
    def split_sides(buttons):
        """Left/right label columns. Keys in the middle band go to whichever
        side has fewer labels near their row, so neither column overflows."""
        sides = {0: [], 1: []}
        middle = []
        for b in buttons:
            cx = b.rect[0] + b.rect[2] / 2
            if abs(cx - 0.5) < CENTRE_BAND:
                middle.append(b)
            else:
                sides[0 if cx < 0.5 else 1].append(b)
        cy = lambda b: b.rect[1] + b.rect[3] / 2
        for b in sorted(middle, key=cy):
            near = [sum(abs(cy(o) - cy(b)) < NEAR_ROWS for o in sides[s]) for s in (0, 1)]
            side = 0 if (near[0], len(sides[0])) <= (near[1], len(sides[1])) else 1
            sides[side].append(b)
        return sides

    def layout_callouts(self):
        self.lines = {}
        self.anchors = {}
        if not self.profile or not self.callouts:
            return
        area = self.image_rect()
        sides = self.split_sides(self.profile.buttons)
        top, bottom = 8.0, self.height() - 8.0
        tallest = 0
        font = QFont(next(iter(self.callouts.values())).font())
        font.setBold(True)  # measure as if selected, so selection never clips
        metrics = QFontMetrics(font)
        for side, buttons in sides.items():
            if not buttons:
                continue
            rows = self._rows(buttons, side, area)
            tallest = max(tallest, len(rows))
            step = LABEL_H + LABEL_GAP
            if step * len(rows) > bottom - top:
                step = (bottom - top) / len(rows)
            # Desired label y = centred on its anchor; then resolve overlaps
            # downward, and pull back up if the column overflows the bottom.
            ys = [anchor.y() - LABEL_H / 2 for _, anchor in rows]
            for i in range(len(ys)):
                ys[i] = max(ys[i], top if i == 0 else ys[i - 1] + step)
            overflow = ys[-1] + LABEL_H - bottom
            if overflow > 0:
                ys[-1] -= overflow
                for i in range(len(ys) - 2, -1, -1):
                    ys[i] = min(ys[i], ys[i + 1] - step)
            # Spare margin goes to the diagonal, so steep leaders spread out.
            margin = area.left() if side == 0 else self.width() - area.right()
            gap = max(COLUMN, margin - LABEL_MAX_W - 10)
            elbow_x = area.left() - ELBOW if side == 0 else area.right() + ELBOW
            column_x = area.left() - gap if side == 0 else area.right() + gap
            room = (column_x - 6) if side == 0 else (self.width() - 6 - column_x)
            for (b, anchor), y in zip(rows, ys):
                label = self.callouts[b.id]
                text = self.label_text(b)
                width = min(metrics.horizontalAdvance(text) + 20, LABEL_MAX_W, max(40, room))
                x = column_x - width if side == 0 else column_x
                label.setGeometry(round(x), round(y), round(width), LABEL_H)
                label.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, round(width) - 16))
                label.show()
                self.anchors[b.id] = anchor
                mid = QPointF(column_x, y + LABEL_H / 2)
                path = QPainterPath(anchor)
                path.lineTo(QPointF(elbow_x, anchor.y()))
                path.lineTo(mid)
                self.lines[b.id] = path
        self.setMinimumHeight(max(520, tallest * (LABEL_H + 2) + 16))

    def resizeEvent(self, event):
        self.layout_callouts()
        super().resizeEvent(event)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        area = self.image_rect()
        if not self.pixmap.isNull():
            painter.drawPixmap(area.toRect(), self.pixmap)
        else:
            painter.setPen(QPen(qcolor("LINE_STRONG"), 1.4, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(area, 16, 16)
            painter.setPen(qcolor("MUTED"))
            font = QFont(painter.font())
            font.setPointSize(11)
            painter.setFont(font)
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             "还没有遥控器照片\n在「名称与位置」里更换照片")
        if not self.profile:
            return
        focus = {self.selection, self.hover}
        # Leaders first (selected/hovered last so they sit on top), then
        # hotspots, then anchor dots, so a line never hides a key outline.
        for b in sorted(self.profile.buttons, key=lambda b: b.id in focus):
            if b.id not in self.lines:
                continue
            strong = b.id in focus
            assigned = b.configurable and any(action.kind != "none" for action in (b.action, b.double_action, b.long_action))
            color = qcolor("ACCENT") if strong else qcolor("ACCENT", 150) if assigned else qcolor("MUTED", 110)
            pen = QPen(color, 1.8 if strong else 1.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(self.lines[b.id])
        for b in self.profile.buttons:
            rect = self.hotspot_rect(b)
            if not b.configurable:
                painter.setPen(QPen(qcolor("FAINT"), 1, Qt.PenStyle.DashLine))
                painter.setBrush(qcolor("INK", 50))
                painter.drawRoundedRect(rect, 7, 7)
                continue
            selected, hovered = b.id == self.selection, b.id == self.hover
            assigned = any(action.kind != "none" for action in (b.action, b.double_action, b.long_action))
            if selected:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(qcolor("ACCENT", 50))
                painter.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), 10, 10)
            fill = qcolor("ACCENT", 90 if selected else 55) if assigned else \
                qcolor("INK", 70) if (selected or hovered or self.edit) else None
            painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            edge = qcolor("ACCENT") if (selected or assigned) else \
                qcolor("PANEL", 200) if hovered else qcolor("MUTED", 120)
            painter.setPen(QPen(edge, 1.8 if selected or hovered else 1.0))
            painter.drawRoundedRect(rect, 7, 7)
        for b in self.profile.buttons:
            if b.id in self.anchors and b.configurable:
                strong = b.id in focus
                assigned = any(action.kind != "none" for action in (b.action, b.double_action, b.long_action))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(qcolor("ACCENT") if strong or assigned else qcolor("MUTED"))
                radius = 3.2 if strong else 2.4
                painter.drawEllipse(self.anchors[b.id], radius, radius)
        if self.origin is not None and self.drag_end is not None:
            start, end = self.origin, self.drag_end
            rect = QRectF(area.x() + min(start[0], end[0]) * area.width(),
                          area.y() + min(start[1], end[1]) * area.height(),
                          abs(start[0] - end[0]) * area.width(),
                          abs(start[1] - end[1]) * area.height())
            painter.setPen(QPen(qcolor("ACCENT"), 1.6, Qt.PenStyle.DashLine))
            painter.setBrush(qcolor("ACCENT", 40))
            painter.drawRect(rect)

    # -- interaction -------------------------------------------------------

    def _normalized(self, point):
        area = self.image_rect()
        return [max(0, min(1, (point.x() - area.x()) / area.width())),
                max(0, min(1, (point.y() - area.y()) / area.height()))]

    def hit_test(self, point):
        if not self.profile:
            return None
        for b in reversed(self.profile.buttons):
            if self.hotspot_rect(b).contains(point):
                return b.id if b.configurable else None
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        configurable = {b.id for b in self.profile.buttons if b.configurable}
        for ident, line in sorted(self.lines.items(), key=lambda x: x[0] == self.selection, reverse=True):
            if ident in configurable and stroker.createStroke(line).contains(point):
                return ident
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.edit and self.image_rect().contains(event.position()):
            self.origin = self._normalized(event.position())
            self.drag_end = self.origin
            return
        ident = self.hit_test(event.position())
        if ident:
            self.selected.emit(ident)
            self.setFocus()

    def mouseDoubleClickEvent(self, event):
        ident = None if self.edit else self.hit_test(event.position())
        if ident:
            self.activated.emit(ident)

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.drag_end = self._normalized(event.position())
            self.update()
        self.set_hover("" if self.origin is not None else (self.hit_test(event.position()) or ""))
        self.setCursor(Qt.CursorShape.CrossCursor if self.edit
                       else Qt.CursorShape.PointingHandCursor if self.hover
                       else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event):
        self.set_hover("")
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.edit and self.origin is not None:
            end = self._normalized(event.position())
            start = self.origin
            self.origin = None
            self.drag_end = None
            rect = [min(start[0], end[0]), min(start[1], end[1]),
                    abs(start[0] - end[0]), abs(start[1] - end[1])]
            if rect[2] > .01 and rect[3] > .01:
                self.region.emit(rect)
            self.update()
