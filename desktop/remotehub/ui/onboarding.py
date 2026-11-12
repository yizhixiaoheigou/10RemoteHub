"""First-run guide: install the reader, grant permission, then map keys.

The three pages avoid jargon: the privileged collector is called a "读取组件"
and its purpose is explained before the button appears. Shown once per profile;
the menu offers "重新运行新手引导…".
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QStackedWidget,
                               QVBoxLayout)

from .. import permissions
from ..branding import APP_NAME
from ..icons import app_icon
from ..controller import StatusView
from ..theme import TOKENS, stylesheet
from .widgets import Pill, button, label, row

PAGES = 3


class OnboardingDialog(QDialog):
    open_mapping = Signal()
    open_settings = Signal()
    open_voice = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.verified = False
        self.c.physical_key.connect(self.verify_key)
        self.setWindowTitle(APP_NAME + " · 开始使用")
        self.setModal(True)
        self.setMinimumWidth(620)
        self.setStyleSheet(stylesheet() + f"""
            QDialog {{ background: {TOKENS['PANEL']}; }}
            QFrame#guideCard {{ background: {TOKENS['SUNKEN']};
                border: 1px solid {TOKENS['LINE']}; border-radius: 12px; }}
            QLabel#guideTitle {{ font-size: 22px; font-weight: 600; }}
            QLabel#guideStep {{ font-size: 15px; font-weight: 600; }}
            QLabel#guideBody {{ color: {TOKENS['MUTED']}; font-size: 13px; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(14)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._welcome())
        self.stack.addWidget(self._prepare())
        self.stack.addWidget(self._done())
        outer.addWidget(self.stack, 1)

        footer = QHBoxLayout()
        self.skip = button("跳过", self.finish)
        footer.addWidget(self.skip)
        footer.addStretch(1)
        self.back = button("上一步", self.back_page)
        self.next = button("下一步", self.next_page, role="primary")
        footer.addWidget(self.back)
        footer.addWidget(self.next)
        outer.addLayout(footer)
        self.show_page(0)

    # -- pages -----------------------------------------------------------------

    def _page(self, title, body, *widgets, icon=None):
        page = QFrame()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        if icon is not None:
            box.addWidget(icon)
            box.addSpacing(2)
        heading = QLabel(title)
        heading.setObjectName("guideTitle")
        heading.setWordWrap(True)
        box.addWidget(heading)
        for text in body:
            paragraph = QLabel(text)
            paragraph.setObjectName("guideBody")
            paragraph.setWordWrap(True)
            box.addWidget(paragraph)
        for widget in widgets:
            box.addWidget(widget)
        box.addStretch(1)
        return page

    def _welcome(self):
        steps = QFrame()
        steps.setObjectName("guideCard")
        box = QVBoxLayout(steps)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)
        for number, text in (("1", "装一个读取组件，让电脑能读到这只遥控器"),
                             ("2", "在遥控器照片上给每个键分配动作"),
                             ("3", "想用遥控器说话时，再打开语音")):
            line = QLabel(f"{number}   {text}")
            line.setObjectName("guideBody")
            box.addWidget(line)
        icon = QLabel()
        icon.setPixmap(app_icon().pixmap(72, 72))
        return self._page("把遥控器变成你的快捷键面板",
                          ["按键怎么用由你决定；说话交给豆包、讯飞这些识别软件。按键和语音内容不上传，仅更新检查和下载会联网。"],
                          steps, icon=icon)

    def _prepare(self):
        self.component_pill = Pill("未检测")
        self.permission_pill = Pill("未检测")
        card = QFrame()
        card.setObjectName("guideCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)
        line = QHBoxLayout()
        heading = QLabel("遥控器读取组件" if sys.platform == "darwin" else "Windows 系统组件")
        heading.setObjectName("guideStep")
        line.addWidget(heading, 1)
        line.addWidget(self.component_pill)
        if sys.platform == "darwin":
            line.addWidget(button("安装", self.install_component))
        box.addLayout(line)
        if sys.platform == "darwin":
            box.addWidget(label("这只接收器是独占的，普通应用打不开，需要在后台装一个小程序来读按键和声音。"
                                "安装要输入一次开机密码。", "caption"))
        else:
            # Windows 没有可安装的读取组件，但有两个第三方件必须由用户装。
            box.addWidget(label("读取按键不需要额外程序；改用遥控器说话前，需要先准备两个第三方组件：", "caption"))
            box.addWidget(label("1. Zadig —— 把接收器的 Interface 3 和 Interface 4 交给本应用读取，只需做一次。", "caption"))
            box.addWidget(label("2. VB-CABLE —— 虚拟麦克风，安装后需要重启电脑。", "caption"))
            box.addWidget(label("Zadig 的说明在「通用设置」，VB-CABLE 在「语音设置」；装完回来点「重新检测」即可。", "caption"))
            box.addWidget(row(button("前往通用设置", self.open_settings.emit),
                              button("前往语音设置", self.open_voice.emit), None))

        if sys.platform != "darwin":
            self.permission_pill.show_status(StatusView("不需要", "", "ok"))
            card2 = None
        else:
            line2 = QHBoxLayout()
            heading2 = QLabel("辅助功能权限")
            heading2.setObjectName("guideStep")
            line2.addWidget(heading2, 1)
            line2.addWidget(self.permission_pill)
            line2.addWidget(button("去授权", lambda: self.c.open_permission("accessibility")))
            card2 = QFrame()
            card2.setObjectName("guideCard")
            box2 = QVBoxLayout(card2)
            box2.setContentsMargins(18, 14, 18, 14)
            box2.setSpacing(8)
            box2.addLayout(line2)
            box2.addWidget(label("用来帮你按快捷键、收起窗口。第一次要在系统设置里勾选。", "caption"))
        widgets = [card] + ([card2] if card2 is not None else [])
        if sys.platform == "darwin":
            self.component_pill.show_status(StatusView("未检测", "", "neutral"))
        else:
            self.component_pill.show_status(StatusView("需准备", "", "neutral"))
        return self._page("第一步：让电脑能读取遥控器",
                          ["两件事都做完，按键才能用。" if sys.platform == "darwin" else
                           "接上接收器；要用遥控器说话时，先准备下面两个组件。"], *widgets)

    def _done(self):
        self.verify_pill = Pill("等待按数字 1")
        self.verify_detail = label("保持数字 1 未设置也可以；这里只确认电脑能收到遥控器信号。", "caption")
        return self._page("第二步：验证遥控器按键",
                          ["现在按一下遥控器上的数字 1。收到信号后，点击「完成」进入按键映射；也可以跳过。"
                           "之后点遥控器照片上的按键，就能分配快捷键、应用、文件或文本。"],
                          self.verify_pill, self.verify_detail)

    def verify_key(self, trigger, down):
        from ..photo_template import KEYMAP
        if self.index != 2 or not down or trigger != KEYMAP["keys"]["tv-number-1"]["trigger"]:
            return
        self.verified = True
        self.verify_pill.show_status(StatusView("按键已验证", "", "ok"))
        self.verify_detail.setText("已收到数字 1 的真实按键信号，遥控器读取链路正常。")

    # -- flow ------------------------------------------------------------------

    def show_page(self, index):
        self.index = max(0, min(PAGES - 1, index))
        self.stack.setCurrentIndex(self.index)
        self.back.setVisible(self.index > 0)
        self.next.setText("完成" if self.index == PAGES - 1 else "下一步")
        if self.index == 1:
            self.refresh()

    def next_page(self):
        if self.index == PAGES - 1:
            self.open_mapping.emit()
            self.finish()
            return
        self.show_page(self.index + 1)

    def back_page(self):
        self.show_page(self.index - 1)

    def install_component(self):
        try:
            self.c.install_collector()
        except Exception as exc:
            self.c.fail(str(exc))
            return
        self.c.tell("已打开安装程序。装好后回到这里，点「下一步」继续。")
        self.refresh()

    def refresh(self):
        self.refresh_component()
        if sys.platform == "darwin":
            state = permissions.permission_status().get("accessibility", "")
            self.permission_pill.show_status(
                StatusView("已授权" if state == "已授权" else "未授权", "",
                           "ok" if state == "已授权" else "neutral"))

    def refresh_component(self):
        if sys.platform == "win32":
            # Windows needs no reader component, but the two third-party pieces
            # decide whether voice works; show whether they are already there.
            ready = []
            try:
                from ..windows_driver import binding_state
                ready.append(binding_state() == "winusb")
            except Exception:
                ready.append(False)
            try:
                from PySide6.QtMultimedia import QMediaDevices
                ready.append(any("cable output" in d.description().casefold()
                                 for d in QMediaDevices.audioInputs()))
            except Exception:
                ready.append(False)
            done = all(ready)
            self.component_pill.show_status(
                StatusView("已就绪" if done else "需准备", "", "ok" if done else "neutral"))
            return
        if sys.platform != "darwin":
            self.component_pill.show_status(StatusView("不需要", "", "ok"))
            return
        try:
            from ..mac_device_helper import installation_status
            code, _ = installation_status()
        except Exception:
            code = 4
        installed = code == 0
        self.component_pill.show_status(
            StatusView("已安装" if installed else "未安装", "", "ok" if installed else "neutral"))

    def finish(self):
        self.c.finish_onboarding()
        self.accept()
