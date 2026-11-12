"""按键映射 page: remote photo canvas on the left, inspector on the right."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..canvas import RemoteCanvas
from ..theme import INSPECTOR_WIDTH
from .inspector import Inspector
from .widgets import button, label, row, scroll


class MappingPage(QWidget):
    title = "按键映射"
    subtitle = "点图上的按键设置功能。语音键固定控制开始和结束，其余按键可分配动作。"

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.setObjectName("page")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(16)

        left = QWidget()
        left.setObjectName("canvasPanel")
        box = QVBoxLayout(left)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.count = label("", "muted", wrap=False)
        self.edit_banner = QLabel("框选模式：在照片上拖出新位置，松手即保存。")
        self.edit_banner.setObjectName("banner")
        self.edit_done = button("完成", lambda: self.inspector.draw.setChecked(False), "quiet")
        self.edit_strip = row(self.edit_banner, self.edit_done, None, spacing=8)
        self.edit_strip.hide()
        box.addWidget(row(self.edit_strip, None, self.count, spacing=8))
        self.canvas = RemoteCanvas()
        box.addWidget(self.canvas, 1)
        box.addWidget(label("单击选择 · 双击或 Enter 编辑动作 · 方向键切换按键 · 虚线框为不能设置的键", "caption"))
        layout.addWidget(left, 1)

        self.inspector = Inspector(controller)
        side = scroll(self.inspector)
        side.setFixedWidth(INSPECTOR_WIDTH)
        layout.addWidget(side)

        self.canvas.selected.connect(self.select_key)
        self.canvas.activated.connect(self.activate)
        self.canvas.region.connect(controller.set_rect)
        self.inspector.edit_mode.connect(self.set_edit)
        controller.mapping_changed.connect(self.refresh)
        controller.profiles_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.canvas.set_profile(self.c.profile, self.c.selected_id)
        done, total = self.c.assigned_count()
        self.count.setText(f"已分配 {done} / {total}")

    def select_key(self, ident):
        if ident == self.c.selected_id:
            return
        if not self.inspector.confirm_text_saved():
            self.refresh()
            return
        self.c.select(ident)

    def activate(self, ident):
        self.select_key(ident)
        if self.c.selected_id == ident:
            self.inspector.focus_editor()

    def set_edit(self, on):
        self.canvas.set_edit(on)
        self.edit_strip.setVisible(on)
