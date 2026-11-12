"""通用设置 page: login startup, permissions and the unified device collector.

Nothing here changes the system until the user clicks: permission rows only
read status and open System Settings; login startup writes only on toggle.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QWidget

from ..branding import APP_NAME
from .. import permissions
from ..controller import StatusView
from .voice import column_page, step_card
from .widgets import Pill, button, hbox, label, row

PERMISSIONS = (("accessibility", "辅助功能", "执行按键和窗口操作"),)


class GeneralPage(QWidget):
    title = "通用设置"
    subtitle = "管理遥控器读取组件、系统授权与登录启动。"

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.c = controller
        self.permission_overlay = None
        self.setObjectName("page")
        steps = column_page(self)

        # -- device component and connection -------------------------------
        card, box, _ = step_card(None, "遥控器与读取组件" if sys.platform == "darwin" else "设备连接")
        self.helper_pill = None
        if sys.platform == "darwin":
            self.helper_pill = Pill("未检测")
            self.helper_pill.setWordWrap(False)
            box.addWidget(self.helper_pill, 0, Qt.AlignmentFlag.AlignLeft)
            box.addWidget(label("读取组件在后台读取这只接收器的按键和声音，安装时需要一次管理员密码。", "caption"))
            self.helper_install = button("安装 / 更新读取组件", self.install_helper, "primary")
            helper_actions = hbox(self.helper_install, button("重新检查权限与连接", self.retry))
            helper_actions.addStretch(1)
            box.addLayout(helper_actions)
            box.addWidget(button("卸载读取组件…", lambda: self.install_helper(True), "link"))
        else:
            self.voice_binding_pill = Pill("未检测")
            self.voice_binding_detail = label("", "caption")
            self.voice_binding_help = label("", "caption")
            self.voice_binding_download = button("前往下载 Zadig", self.open_zadig_page)
            self.voice_binding_launch = button("绑定语音接口", self.install_voice_binding)
            box.addWidget(row(label("遥控器语音接口", wrap=False), None, self.voice_binding_pill,
                              self.voice_binding_download, spacing=8))
            box.addWidget(self.voice_binding_detail)
            box.addWidget(self.voice_binding_help)
            box.addWidget(row(self.voice_binding_launch, button("重新检查权限与连接", self.retry), None))
        self.connection_status = Pill()
        self.connection_status.setWordWrap(False)
        box.addWidget(self.connection_status, 0, Qt.AlignmentFlag.AlignLeft)
        self.connection_detail = label("", "caption")
        box.addWidget(self.connection_detail)
        self.connection_error = label("", "caption")
        self.connection_error.setTextFormat(Qt.TextFormat.PlainText)
        self.connection_error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.connection_error.setAccessibleName("设备接入原始错误")
        box.addWidget(self.connection_error)
        steps.addWidget(card)

        # -- permissions ---------------------------------------------------
        card, box, _ = step_card(None, "系统授权")
        self.permission_rows = {}
        if sys.platform == "darwin":
            box.addWidget(label(f"点击「前往授权」，在系统设置里为 {APP_NAME} 打开开关。", "caption"))
            for key, title, purpose in PERMISSIONS:
                pill = Pill("尚未检测")
                self.permission_rows[key] = pill
                box.addWidget(row(label(f"{title} · {purpose}", wrap=False), None, pill,
                                  button("前往授权", lambda k=key: self.c.open_permission(k)), spacing=8))
            bundle = permissions.running_app_bundle()
            if bundle:
                box.addWidget(label("系统设置底部会出现拖拽引导，把应用图标拖入列表后再打开开关。", "caption"))
                box.addWidget(label("列表里已有本应用时，直接确认开关已打开；改完点「重新检查权限与连接」。", "caption"))
            else:
                box.addWidget(label("列表里没有本应用时，用「＋」添加，再打开开关。", "caption"))
        else:
            box.addWidget(label("Windows 普通按键映射没有 macOS 式授权开关；受保护或以管理员身份运行的应用可能拒绝模拟按键。", "caption"))
        steps.addWidget(card)

        # System shortcuts are cached at launch; this button is the only refresh.
        self.hotkey_labels = {}
        if sys.platform == "darwin":
            from ..system_hotkeys import OPERATIONS, GROUPS
            card, box, _ = step_card(None, "系统快捷键")
            box.addWidget(label("每次启动时自动读取。修改 macOS 键盘快捷键后，点击「重新读取」更新。", "caption"))
            self.hotkeys_reload = button("重新读取", self.reload_hotkeys)
            box.addWidget(self.hotkeys_reload, 0, Qt.AlignmentFlag.AlignLeft)
            for group, operations in GROUPS:
                box.addWidget(label(group, "caption"))
                for operation in operations:
                    title = OPERATIONS[operation][1]
                    value = label("", "caption")
                    value.setAccessibleName(title + "当前快捷键")
                    self.hotkey_labels[operation] = value
                    box.addWidget(row(label(title, wrap=False), None, value))
            steps.addWidget(card)
            self.show_hotkeys()

        # -- startup -------------------------------------------------------
        card, box, _ = step_card(None, "启动与后台运行")
        self.start_at_login = QCheckBox("登录后自动启动")
        self.start_at_login.toggled.connect(self.set_autostart)
        box.addWidget(self.start_at_login)
        self.startup_status = label("", "caption")
        box.addWidget(self.startup_status)
        box.addWidget(label("关闭窗口后仍在后台运行；从状态栏选择「退出」即可停止。", "caption"))
        steps.addWidget(card)

        controller.device_changed.connect(self.refresh)
        controller.permission_opened.connect(self.show_permission_overlay)
        self.refresh()
        self.refresh_autostart()

    def show_hotkeys(self):
        cache = self.c.runner.system_hotkeys
        if cache is not None:
            for operation, value in self.hotkey_labels.items():
                value.setText(cache.status(operation))

    def reload_hotkeys(self):
        self.c.runner.system_hotkeys.refresh()
        self.show_hotkeys()
        self.c.tell("已重新读取系统快捷键；未修改 macOS 设置。")

    def on_show(self):
        """Called when the page becomes visible; status reads are cheap and read-only."""
        self.refresh_permissions()
        self.refresh_autostart()
        self.refresh_helper()

    def refresh(self):
        c = self.c
        connection = c.device_view()
        self.connection_status.show_status(connection)
        self.connection_detail.setText(connection.detail)
        self.connection_error.setText("具体错误：" + connection.diagnostic if connection.diagnostic else "")
        self.connection_error.setVisible(bool(connection.diagnostic))
        self.refresh_voice_binding()

    def refresh_permissions(self):
        states = self.c.permission_status()
        for key, pill in self.permission_rows.items():
            text = states.get(key, "无法检测")
            tone = "ok" if text == "已授权" else "error" if text == "未授权" else "neutral"
            pill.show_status(StatusView(text, "", tone))

    def refresh_autostart(self):
        try:
            enabled = self.c.autostart_enabled()
            self.start_at_login.blockSignals(True)
            self.start_at_login.setChecked(enabled)
            self.start_at_login.blockSignals(False)
            self.startup_status.setText("已设置登录启动" if enabled else "未设置登录启动")
        except Exception as exc:
            self.startup_status.setText("无法读取登录启动设置：" + str(exc))

    def set_autostart(self, enabled):
        try:
            self.c.set_autostart(enabled)
            self.refresh_autostart()
        except Exception as exc:
            self.start_at_login.blockSignals(True)
            self.start_at_login.setChecked(not enabled)
            self.start_at_login.blockSignals(False)
            self.startup_status.setText("登录启动设置失败：" + str(exc))

    def refresh_helper(self):
        if self.helper_pill is not None:
            from ..mac_device_helper import installation_status
            code, message = installation_status()
            self.helper_pill.show_status(StatusView(message, "", "ok" if code == 0 else "neutral"))

    def open_zadig_page(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://zadig.akeo.ie/"))

    def install_voice_binding(self):
        """Launch a local Zadig when present; otherwise explain inline."""
        from ..windows_driver import binding_state, helper_path, helper_path, launch_helper
        if binding_state() == "winusb":
            self.c.tell("语音接口已绑定，无需重复操作。")
            return
        if helper_path() is None:
            self.c.tell("没有随程序提供 Zadig。请先点「前往下载 Zadig」，按上方三步绑定一次。")
            return
        try:
            self.c.tell(launch_helper())
        except Exception as exc:
            self.c.fail(str(exc))
        self.refresh_voice_binding()

    def refresh_voice_binding(self):
        if sys.platform != "win32" or not hasattr(self, "voice_binding_pill"):
            return
        from ..windows_driver import binding_state, helper_path
        state = binding_state()
        bound = state == "winusb"
        if bound:
            self.voice_binding_pill.show_status(StatusView("已绑定", "", "ok"))
            self.voice_binding_detail.setText("按键和语音都由应用独占接收器，接收器不会因语音键掉线。")
        elif state == "missing":
            self.voice_binding_pill.show_status(StatusView("接收器未接入", "", "neutral"))
            self.voice_binding_detail.setText("把接收器插到电脑后再绑定。")
        else:
            self.voice_binding_pill.show_status(StatusView("未绑定", "", "neutral"))
            self.voice_binding_detail.setText("按键和语音需要接收器的两个接口交给本应用读取。")
        self.voice_binding_help.setText(
            "" if bound else
            "安装 Zadig 后勾选 Options → List All Devices，先选「Interface 3」、驱动选 WinUSB、"
            "点 Replace Driver；再对「Interface 4」做一次。只需做一次，随时可在设备管理器卸载恢复。")
        self.voice_binding_help.setVisible(not bound)
        self.voice_binding_download.setVisible(not bound)
        self.voice_binding_launch.setVisible(not bound and helper_path() is not None)

    def install_helper(self, remove=False):
        if remove:
            from PySide6.QtWidgets import QMessageBox
            answer = QMessageBox.question(
                self, "卸载读取组件", "卸载后，按键映射和遥控器语音都会停止。确定继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self.c.install_collector(remove)
            self.c.tell("已打开读取组件的卸载程序。" if remove else "已打开安装程序，装好后点「重新检查权限与连接」。")
        except Exception as exc:
            self.c.fail(str(exc))

    def retry(self):
        self.refresh_helper()
        self.refresh_permissions()
        self.c.retry_connection()

    def show_permission_overlay(self, name):
        bundle = permissions.running_app_bundle()
        if bundle is None:
            return
        # The drag target sits in the Settings window, so the main window steps
        # aside instead of covering it; the guide panel is a separate tool window.
        window = self.window()
        if window is not None and window.isVisible() and not window.isMinimized():
            window.showMinimized()
        if self.permission_overlay is None:
            from .permission_overlay import PermissionOverlay
            self.permission_overlay = PermissionOverlay(bundle)
            self.permission_overlay.failed.connect(self.c.fail)
            self.permission_overlay.authorized.connect(self.refresh_permissions)
        self.permission_overlay.begin(name)

    def close_permission_overlay(self):
        if self.permission_overlay is not None:
            self.permission_overlay.close()
