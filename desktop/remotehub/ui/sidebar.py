"""Left rail: brand, page navigation, device card, import/export."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFileDialog, QFrame, QVBoxLayout, QWidget

from ..branding import APP_NAME
from ..theme import SIDEBAR_WIDTH
from .widgets import Pill, ScrollSafeComboBox, button, label, row


class Sidebar(QWidget):
    page_requested = Signal(int)
    retry_requested = Signal()
    settings_requested = Signal()

    def __init__(self, controller, pages, parent=None):
        super().__init__(parent)
        self.c = controller
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(SIDEBAR_WIDTH)
        side = QVBoxLayout(self)
        side.setContentsMargins(16, 22, 16, 16)
        side.setSpacing(6)
        brand = label(APP_NAME, wrap=False)
        brand.setObjectName("brand")
        sub = label("遥控器 · 按键 · 语音")
        sub.setObjectName("brandSub")
        side.addWidget(brand)
        side.addWidget(sub)
        side.addSpacing(18)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for index, (title, shortcut) in enumerate(pages):
            nav = button(title, lambda i=index: self.page_requested.emit(i), "nav")
            nav.setCheckable(True)
            nav.setToolTip(shortcut)
            self.nav.addButton(nav, index)
            side.addWidget(nav)
        side.addSpacing(18)

        side.addWidget(label("设备", "caption"))
        card = QFrame()
        card.setObjectName("deviceCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(8)
        self.profile_box = ScrollSafeComboBox()
        self.profile_box.setAccessibleName("选择遥控器配置")
        self.profile_box.activated.connect(self.select_profile)
        self.manage_profile = button("管理…", self.manage_profiles, "quiet")
        box.addWidget(row(self.profile_box, self.manage_profile))
        self.device_name = label("", "value", wrap=False)
        self.device_name.setAccessibleName("当前设备")
        box.addWidget(self.device_name)
        self.status = Pill("尚未检测")
        self.status.setAccessibleName("USB 连接状态")
        box.addWidget(self.status)
        self.detail = label("", "caption")
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.detail)
        self.settings = button("前往通用设置", self.settings_requested.emit, "link")
        box.addWidget(self.settings)
        # Key input starts by itself; there is no enable switch. A failed
        # attempt waits for 重新检测 (or a replug) instead of retrying every scan.
        box.addWidget(button("重新检测", self.retry_requested.emit, "link"))
        side.addWidget(card)
        side.addStretch(1)

        side.addWidget(label("配置保存在这台电脑", "caption"))
        side.addWidget(row(button("导入按键…", self.import_profile, "quiet"),
                           button("导出按键…", self.export_profile, "quiet"), spacing=6))

        controller.profiles_changed.connect(self.refresh_profiles)
        controller.device_changed.connect(self.refresh_device)
        self.refresh_profiles()

    def set_page(self, index):
        self.nav.button(index).setChecked(True)

    def refresh_profiles(self):
        names = self.c.profile_names()
        self.profile_box.blockSignals(True)
        self.profile_box.clear()
        for name in names:
            self.profile_box.addItem(name)
        self.profile_box.setCurrentIndex(self.c.index)
        self.profile_box.blockSignals(False)
        # A single built-in profile needs no picker; show it as plain text.
        multiple = len(names) > 1
        self.profile_box.setVisible(multiple)
        self.manage_profile.setVisible(multiple)
        self.device_name.setVisible(not multiple)
        self.device_name.setText(names[self.c.index] if names else "")
        self.refresh_device()

    def refresh_device(self):
        view = self.c.device_view()
        self.status.show_status(view)
        self.detail.setText(view.detail)
        self.detail.setToolTip(view.diagnostic)
        self.settings.setVisible(view.settings_link)

    def confirm_text_saved(self):
        inspector = getattr(self.window(), "inspector", None)
        return inspector is None or inspector.confirm_text_saved()

    def select_profile(self, index):
        if index == self.c.index:
            return
        if not self.confirm_text_saved():
            self.profile_box.setCurrentIndex(self.c.index)
            return
        self.c.select_profile(index)

    def import_profile(self):
        if not self.confirm_text_saved():
            return
        path = QFileDialog.getOpenFileName(self, "导入按键配置", "", "按键配置 (*.json)")[0]
        if not path:
            return
        from PySide6.QtWidgets import QMessageBox
        dialog = QMessageBox(self)
        dialog.setWindowTitle("导入按键配置")
        dialog.setText("替换当前配置，还是保留为一个新配置？语音设置不受影响。")
        replace = dialog.addButton("替换当前配置", QMessageBox.ButtonRole.AcceptRole)
        append = dialog.addButton("保留为新配置", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() == replace:
            self.c.import_profile(path, replace=True)
        elif dialog.clickedButton() == append:
            self.c.import_profile(path)

    def manage_profiles(self):
        from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox
        menu = QMenu(self)
        rename = menu.addAction("重命名当前配置…")
        delete = menu.addAction("删除当前配置…")
        chosen = menu.exec(self.manage_profile.mapToGlobal(self.manage_profile.rect().bottomLeft()))
        if chosen == rename:
            name, ok = QInputDialog.getText(self, "重命名按键配置", "配置名称", text=self.c.profile.name)
            if ok:
                self.c.rename_profile(name)
        elif chosen == delete:
            answer = QMessageBox.question(self, "删除按键配置", f"确定删除「{self.c.profile.name}」吗？此操作不能撤销。",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Yes:
                self.c.delete_profile()

    def export_profile(self):
        if not self.confirm_text_saved():
            return
        path = QFileDialog.getSaveFileName(self, "导出按键配置", self.c.profile.name.replace(":", "-").replace("/", "-").replace("\\", "-") + ".json", "按键配置 (*.json)")[0]
        if path:
            self.c.export_profile(path)
