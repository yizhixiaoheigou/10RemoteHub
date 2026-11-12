"""Right-hand inspector: edit the selected key's action in place.

Layout (top → bottom): single/double/long gesture · key name and current
action · value editor · 清除映射 · grouped action palette ·
(non-fixed models only) name, position and photo.

Commit rule: an action is saved the moment it is complete. Palette entries
without a value save on click; 按键 / 组合键, 打开 / 收起 App and 打开文件
save once their value is recorded or picked. Text is committed with 保存文本.
Unsaved text prompts before switching keys, actions or gestures.
"""
from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QGridLayout, QKeySequenceEdit, QLineEdit,
    QPlainTextEdit, QStackedWidget, QVBoxLayout, QWidget,
)

from ..gestures import KeyGesture
from ..model import Action
from ..presentation import action_text, chip_hint, chip_id, palette
from ..theme import INSPECTOR_WIDTH
from .widgets import button, keys_sequence, label, row, rule, sequence_keys, set_invalid, set_role
from .voice import VoiceKeyEditor, combo

PAGES = {"shortcut": 1, "app": 2, "toggle_app": 2, "file": 3, "text": 4, "hold": 5, "latch": 5}


def choose_application(parent):
    if sys.platform == "darwin":
        # Cocoa treats .app bundles as selectable files, not navigable folders.
        # Directory-only mode disables them in the native open panel.
        return QFileDialog.getOpenFileName(parent, "选择应用程序", "/Applications", "应用程序 (*.app)")[0]
    return QFileDialog.getOpenFileName(parent, "选择应用程序", "", "应用程序 (*.exe);;所有文件 (*)")[0]


def choose_file(parent):
    return QFileDialog.getOpenFileName(parent, "选择要打开的文件")[0]


def action_for_chip(ident):
    if ident.startswith("common:"):
        return Action("common", target=ident.split(":", 1)[1])
    return Action(ident)


class Inspector(QWidget):
    edit_mode = Signal(bool)
    voice_settings_requested = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.gesture = "single"
        self.draft_kind = None   # chosen but not yet complete
        self.draft_app = ""      # file "open with" picked before the file
        self.shown_id = None
        self.loading = False
        self.text_context = None
        self.setObjectName("panel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(INSPECTOR_WIDTH - 12)
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(10)

        self.gesture_buttons = {}
        gesture_controls = []
        for name, title in (("single", "单击"), ("double", "双击"), ("long", "长按")):
            control = button(title, lambda checked=False, g=name: self.set_gesture(g), "kind")
            control.setCheckable(True)
            self.gesture_buttons[name] = control
            gesture_controls.append(control)
        box.addWidget(row(*gesture_controls, spacing=4))
        self.gesture_hint = label("", "caption")
        box.addWidget(self.gesture_hint)

        self.title = label("选择一个按键", "heading")
        self.summary = label("在图上点一个键", "muted")
        box.addWidget(self.title)
        box.addWidget(self.summary)
        self.voice_editor = VoiceKeyEditor(controller)
        box.addWidget(self.voice_editor)
        self.voice_settings = button("更多语音设置", self.voice_settings_requested.emit, "link")
        box.addWidget(self.voice_settings)
        self.pages = QStackedWidget()
        self.pages.addWidget(QWidget())               # 0: no value needed
        self.pages.addWidget(self._shortcut_page())   # 1
        self.pages.addWidget(self._app_page())        # 2
        self.pages.addWidget(self._file_page())       # 3
        self.pages.addWidget(self._text_page())       # 4
        self.pages.addWidget(self._modifier_page())   # 5
        box.addWidget(self.pages)
        self.hint = label("", "caption")
        box.addWidget(self.hint)
        self.clear_current = button("", lambda: self.c.clear_action(self.gesture), "danger")
        self.clear_current.setToolTip("只清除当前手势；另外两种手势的设置保留")
        self.test = button("测试", self.test_clicked)
        box.addWidget(row(self.clear_current, None, self.test, spacing=6))
        self.action_divider = rule()
        box.addWidget(self.action_divider)

        self.kinds = {}
        self.action_palette = QWidget()
        palette_box = QVBoxLayout(self.action_palette)
        palette_box.setContentsMargins(0, 0, 0, 0)
        palette_box.setSpacing(10)
        box.addWidget(self.action_palette)
        palette_box.addWidget(label("选择当前手势要执行的动作", "caption"))
        for n, (group, items) in enumerate(palette()):
            if n:
                palette_box.addSpacing(2)
            palette_box.addWidget(label(group, "caption"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(2)
            for i, (ident, title) in enumerate(items):
                control = button(title, lambda k=ident: self.choose_kind(k), "kind")
                control.setCheckable(True)
                control.setToolTip(chip_hint(ident))
                self.kinds[ident] = control
                grid.addWidget(control, i // 2, i % 2)
            palette_box.addLayout(grid)

        self.details_divider = rule()
        box.addWidget(self.details_divider)
        self.more = button("▸ 名称与位置", self.toggle_details, "disclosure")
        self.more.setCheckable(True)
        box.addWidget(self.more)
        self.details = self._details()
        self.details.hide()
        box.addWidget(self.details)
        box.addStretch(1)

        controller.mapping_changed.connect(self.refresh)
        controller.profiles_changed.connect(self.refresh)
        controller.learning_changed.connect(lambda on: self.refresh())
        controller.test_pending.connect(self.show_test)
        self.refresh()

    # -- parameter pages -------------------------------------------------

    def _text_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(6)
        box.addWidget(label("要输入的文本", "caption"))
        self.text_input = QPlainTextEdit()
        self.text_input.setAccessibleName("要输入的文本")
        self.text_input.setPlaceholderText("例如 CODEX，支持中文和多行文本")
        self.text_input.setFixedHeight(110)
        self.text_input.setTabChangesFocus(True)
        self.text_input.textChanged.connect(self.text_edited)
        box.addWidget(self.text_input)
        self.text_error = label("", wrap=True)
        self.text_error.setObjectName("inlineError")
        self.text_error.hide()
        box.addWidget(self.text_error)
        self.text_save = button("保存文本", self.save_text)
        box.addWidget(row(self.text_save, None))
        return page

    @property
    def text_dirty(self):
        return bool(self.visible_kind == "text" and self.text_context is not None
                    and self.text_input.toPlainText() != self.text_context[2])

    def text_edited(self):
        if self.loading:
            return
        self.text_error.hide()
        set_invalid(self.text_input, False)
        self._fit_pages()
        self.text_save.setEnabled(self.text_dirty)
        if self.text_dirty:
            self.summary.setText("未保存 · 原动作保留：" + action_text(self.current_action))
        else:
            self.refresh()

    def save_text(self):
        if self.c.selected is None or self.c.selected_voice_key or self.visible_kind != "text":
            return False
        action = Action("text", text=self.text_input.toPlainText())
        try:
            action.validate()
        except ValueError as exc:
            self.text_error.setText(str(exc))
            self.text_error.show()
            set_invalid(self.text_input, True)
            self._fit_pages()
            return False
        if self.c.assign(action, self.gesture):
            self.draft_kind = None
            self.refresh()
            return True
        return False

    def confirm_text_saved(self):
        if not self.text_dirty:
            return True
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            self, "未保存的文本", "当前文本尚未保存。离开前要保存吗？",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save_text()
        return answer == QMessageBox.StandardButton.Discard

    def _shortcut_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(6)
        self.sequence = QKeySequenceEdit()
        self.sequence.setMaximumSequenceLength(1)
        self.sequence.setAccessibleName("录制快捷键")
        self.sequence.setToolTip("点击后按下快捷键；松手自动保存")
        self.sequence.editingFinished.connect(self.sequence_done)
        self.sequence_error = label("", wrap=True)
        self.sequence_error.setObjectName("inlineError")
        self.sequence_error.hide()
        box.addWidget(self.sequence)
        box.addWidget(self.sequence_error)
        return page

    def _modifier_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        self.modifier = combo((("cmd", "Command"), ("ctrl", "Control"),
                               ("alt", "Option / Alt"), ("shift", "Shift")), "选择要保持的键")
        self.modifier.activated.connect(self.modifier_chosen)
        box.addWidget(self.modifier)
        return page

    def modifier_chosen(self):
        if self.visible_kind in ("hold", "latch"):
            self._commit(Action("hold", target=self.visible_kind,
                                keys=[self.modifier.currentData()]))

    def _app_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(6)
        self.app_target = QLineEdit()
        self.app_target.setReadOnly(True)
        self.app_target.setPlaceholderText("尚未选择应用")
        self.app_target.setAccessibleName("要打开的应用")
        box.addWidget(row(self.app_target, button("选择…", self.pick_app), spacing=6))
        return page

    def _file_page(self):
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(6)
        self.file_target = QLineEdit()
        self.file_target.setReadOnly(True)
        self.file_target.setPlaceholderText("尚未选择文件")
        self.file_target.setAccessibleName("要打开的文件")
        box.addWidget(row(self.file_target, button("选择…", self.pick_file), spacing=6))
        self.file_app = label("", "caption")
        box.addWidget(self.file_app)
        box.addWidget(row(button("指定打开方式…", self.pick_file_app, "link"),
                          button("系统默认", self.default_file_app, "link"), None, spacing=14))
        return page

    def _details(self):
        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(0, 2, 0, 0)
        box.setSpacing(8)
        box.addWidget(label("名称", "caption"))
        self.name = QLineEdit()
        self.name.setAccessibleName("按键名称")
        self.name.editingFinished.connect(lambda: self.c.rename(self.name.text()))
        box.addWidget(self.name)
        box.addWidget(label("实体按键", "caption"))
        self.trigger = label("", "muted")
        self.trigger.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.learn = button("学习实体按键", self.c.toggle_learning)
        box.addWidget(self.trigger)
        box.addWidget(self.learn)
        box.addWidget(label("在图片上的位置（%）", "caption"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.rect_spins = []
        for i, title in enumerate(("X", "Y", "宽", "高")):
            spin = QDoubleSpinBox()
            spin.setRange(0, 100)
            spin.setDecimals(1)
            spin.setPrefix(title + "  ")
            spin.setAccessibleName({"X": "横向位置", "Y": "纵向位置", "宽": "宽度", "高": "高度"}[title] + " %")
            spin.valueChanged.connect(self.rect_edited)
            grid.addWidget(spin, i // 2, i % 2)
            self.rect_spins.append(spin)
        box.addLayout(grid)
        self.draw = QCheckBox("在图上框选位置")
        self.draw.toggled.connect(self.edit_mode)
        box.addWidget(self.draw)
        box.addWidget(label("照片", "caption"))
        box.addWidget(row(button("更换照片…", self.pick_photo), None, spacing=6))
        self.custom = row(button("添加按键", self.c.add_button), button("移除这个键", self.c.remove_button, "danger"),
                          None, spacing=6)
        box.addWidget(self.custom)
        return panel

    # -- state -> widgets -------------------------------------------------

    @property
    def current_action(self):
        button = self.c.selected
        if button is None:
            return Action()
        field = {"single": "action", "double": "double_action", "long": "long_action"}[self.gesture]
        return getattr(button, field)

    def set_gesture(self, gesture):
        if gesture == self.gesture:
            return
        if self.c.selected_voice_key or not self.confirm_text_saved():
            self.refresh()
            return
        self.gesture = gesture
        self.draft_kind, self.draft_app = None, ""
        self.text_context = None
        self.refresh()

    @property
    def visible_kind(self):
        """Chip id shown as current: the draft if any, else the saved action."""
        if self.c.selected is None:
            return None
        return self.draft_kind or chip_id(self.current_action)

    def _fit_pages(self):
        height = self.pages.currentWidget().sizeHint().height() if not self.pages.isHidden() else 0
        self.pages.setFixedHeight(max(0, height))

    def refresh(self):
        self.loading = True
        if self.c.selected_voice_key and self.gesture != "single":
            self.gesture = "single"
            self.draft_kind, self.draft_app = None, ""
            self.text_context = None
        b = self.c.selected
        if b is None or b.id != self.shown_id:
            self.draft_kind, self.draft_app = None, ""
            self.shown_id = b.id if b else None
            set_invalid(self.sequence, False)
            self.sequence_error.hide()
        kind = self.visible_kind
        fixed = self.c.fixed_model
        reserved_voice = self.c.selected_voice_key
        self.voice_editor.setVisible(reserved_voice)
        self.voice_settings.setVisible(reserved_voice)
        self.action_palette.setVisible(not reserved_voice)
        self.action_divider.setVisible(not reserved_voice)
        self.clear_current.setVisible(not reserved_voice)
        self.title.setText(b.name if b else "选择一个按键")
        gesture_name = {"single": "单击", "double": "双击", "long": "长按"}[self.gesture]
        self.gesture_hint.setText({
            "single": "当前编辑：单击动作。",
            "double": f"当前编辑：双击动作。快速按两次执行，单击需等待 {KeyGesture.DOUBLE_INTERVAL} ms 区分。",
            "long": f"当前编辑：长按动作。按住 {KeyGesture.LONG_PRESS} ms 执行，短按仍执行单击。",
        }[self.gesture])
        self.clear_current.setText(f"清除{gesture_name}映射")
        if b is None:
            self.summary.setText("在图上点一个键，或用 Tab / 方向键选择。")
        elif reserved_voice:
            self.summary.setText("专用语音键 · 开始 / 结束")
        elif self.text_dirty:
            self.summary.setText(f"{gesture_name}动作 · 未保存，原动作保留：" + action_text(self.current_action))
        elif self.draft_kind:
            self.summary.setText(f"{gesture_name}动作 · 未完成，原动作保留：" + action_text(self.current_action))
        else:
            self.summary.setText(gesture_name + "动作：" +
                                 (action_text(self.current_action) if self.current_action.kind != "none" else "未设置"))
        for name, control in self.gesture_buttons.items():
            control.setChecked(name == self.gesture)
            control.setEnabled(b is not None and (name == "single" or not reserved_voice))
        for ident, control in self.kinds.items():
            control.setEnabled(b is not None and not reserved_voice)
            control.setChecked(ident == kind)
            if ident == "voice":
                control.setVisible(not fixed)
        page = PAGES.get(kind or "", 0)
        for i in range(self.pages.count()):
            self.pages.widget(i).setVisible(i == page)
        self.pages.setCurrentIndex(page)
        self.pages.setVisible(page != 0 and not reserved_voice)
        action = self.current_action if b else Action()
        context = (b.id if b else None, kind, action.text if action.kind == "text" else "")
        if context != self.text_context:
            self.text_context = context
            self.text_input.setPlainText(context[2])
            self.text_error.hide()
            set_invalid(self.text_input, False)
        self.text_save.setEnabled(self.text_dirty)
        if not self.sequence.hasFocus():
            self.sequence.setKeySequence(keys_sequence(action.keys if action.kind == "shortcut" else []))
        self.app_target.setText(action.target if action.kind in ("app", "toggle_app") else "")
        self.file_target.setText(action.target if action.kind == "file" else "")
        file_app = action.application if action.kind == "file" else self.draft_app
        self.file_app.setText("打开方式：" + (Path(file_app).name if file_app else "系统默认"))
        modifier = action.keys[0] if action.kind == "hold" and action.keys else "cmd"
        self.modifier.setCurrentIndex(max(0, self.modifier.findData(modifier)))
        self.hint.setText(chip_hint(kind or "none") if b else "")
        self.hint.setVisible(not reserved_voice)
        self.clear_current.setEnabled(bool(b and self.current_action.kind != "none"))
        # The fixed remote is a finished product: no delayed test, key codes,
        # names, geometry or photo controls. Those stay for other models.
        self.test.setVisible(not fixed)
        for widget in (self.details_divider, self.more):
            widget.setVisible(not fixed)
        if fixed and (self.more.isChecked() or self.draw.isChecked()):
            self.more.setChecked(False)
            self.toggle_details()
        self.show_test(self.c.test_left if self.c.test_timer.isActive() else 0)
        if not self.name.hasFocus():
            self.name.setText(b.name if b else "")
        self.name.setEnabled(b is not None)
        self.trigger.setText((b.trigger or "尚未学习") if b else "")
        self.learn.setVisible(not fixed)
        self.learn.setEnabled(b is not None)
        self.learn.setText("取消学习" if self.c.learning else "学习实体按键")
        set_role(self.learn, "pending" if self.c.learning else None)
        for i, spin in enumerate(self.rect_spins):
            spin.setEnabled(b is not None)
            spin.setValue(b.rect[i] * 100 if b else 0)
        self.draw.setEnabled(b is not None)
        self._fit_pages()
        self.loading = False

    def show_test(self, seconds):
        b = self.c.selected
        if seconds:
            self.test.setText(f"取消（{seconds}）")
            set_role(self.test, "pending")
            self.test.setEnabled(True)
            return
        self.test.setText("测试")
        set_role(self.test, None)
        self.test.setEnabled(bool(b and self.current_action.kind not in ("none", "voice") and not self.draft_kind))
        self.test.setToolTip("语音动作请在「语音设置」页验证" if b and self.current_action.kind == "voice"
                             else "3 秒后在当前前台应用执行一次这个动作")

    # -- intents -----------------------------------------------------------

    def choose_kind(self, ident):
        b = self.c.selected
        if b is None or self.c.selected_voice_key:
            return
        if ident == self.visible_kind:
            return
        if not self.confirm_text_saved():
            self.refresh()
            return
        current = self.current_action
        if ident == chip_id(current):
            self.draft_kind = None
        elif ident not in PAGES:
            self.draft_kind = None
            self.c.assign(action_for_chip(ident), self.gesture)
        elif {ident, current.kind} == {"app", "toggle_app"} and current.target:
            self.draft_kind = None
            self.c.assign(Action(ident, target=current.target), self.gesture)
        else:
            self.draft_kind = ident
        self.refresh()
        if self.draft_kind == "shortcut":
            self.sequence.setFocus()
        elif self.visible_kind == "text":
            self.text_input.setFocus()

    def _commit(self, action):
        self.draft_kind, self.draft_app = None, ""
        if not self.c.assign(action, self.gesture):
            self.refresh()

    def sequence_done(self):
        if self.loading:
            return
        keys = sequence_keys(self.sequence.keySequence())
        b = self.c.selected
        if not keys or b is None:
            return
        try:
            Action("shortcut", keys).validate(sys.platform)
        except ValueError as exc:
            self.sequence_error.setText(str(exc))
            self.sequence_error.show()
            set_invalid(self.sequence, True)
            self._fit_pages()
            return
        self.sequence_error.hide()
        set_invalid(self.sequence, False)
        if self.current_action.kind == "shortcut" and self.current_action.keys == keys:
            self.draft_kind = None
            self.refresh()
            return
        self._commit(Action("shortcut", keys))

    def pick_app(self):
        path = choose_application(self)
        if path:
            kind = self.visible_kind if self.visible_kind in ("app", "toggle_app") else "toggle_app"
            self._commit(Action(kind, target=path))

    def pick_file(self):
        path = choose_file(self)
        if not path:
            return
        b = self.c.selected
        app = self.current_action.application if b and self.current_action.kind == "file" else self.draft_app
        self._commit(Action("file", target=path, application=app))

    def pick_file_app(self):
        path = choose_application(self)
        if path:
            self._set_file_app(path)

    def default_file_app(self):
        self._set_file_app("")

    def _set_file_app(self, path):
        b = self.c.selected
        if b and self.current_action.kind == "file" and not self.draft_kind:
            self._commit(Action("file", target=self.current_action.target, application=path))
        else:
            self.draft_app = path
            self.refresh()

    def rect_edited(self):
        if not self.loading:
            self.c.set_rect([s.value() / 100 for s in self.rect_spins])

    def pick_photo(self):
        path = QFileDialog.getOpenFileName(self, "选择遥控器实物照片", "", "图片 (*.png *.jpg *.jpeg *.webp)")[0]
        if path:
            self.c.replace_photo(path)

    def test_clicked(self):
        if self.c.test_timer.isActive():
            self.c.cancel_test()
        else:
            self.c.schedule_test()

    def toggle_details(self):
        open_ = self.more.isChecked()
        self.more.setText(("▾ " if open_ else "▸ ") + "名称与位置")
        self.details.setVisible(open_)
        if not open_ and self.draw.isChecked():
            self.draw.setChecked(False)

    def focus_editor(self):
        """Enter / double-click on the canvas: jump to the most useful control."""
        if self.c.selected_voice_key:
            self.voice_editor.shortcut.setFocus()
            return
        kind = self.visible_kind
        if kind == "shortcut":
            self.sequence.setFocus()
        elif kind == "text":
            self.text_input.setFocus()
        elif kind in self.kinds:
            self.kinds[kind].setFocus()
        else:
            self.kinds["shortcut"].setFocus()
