"""Main window shell: sidebar | header + page stack + feedback bar, plus tray."""
from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)
from platformdirs import user_config_path

from ..branding import APP_NAME
from ..controller import AppController
from ..icons import app_icon, tray_icon, set_dock_visible
from ..theme import apply_theme
from .general import GeneralPage
from .mapping import MappingPage
from .sidebar import Sidebar
from .voice import VoicePage
from .widgets import button, label, scroll

DEFAULT_SIZE = (1280, 840)
MINIMUM_SIZE = (1200, 720)


class MainWindow(QMainWindow):
    def __init__(self, directory=None, safe=False):
        super().__init__()
        directory = Path(directory) if directory else user_config_path("RemoteHub", appauthor=False)
        self.controller = c = AppController(directory, self, auto_mapping=not safe)
        c.host = self
        self.tray = None
        self.setWindowTitle(APP_NAME + " · 遥控器与语音")
        self.setWindowIcon(app_icon())
        apply_theme(self)
        self.setMinimumSize(*MINIMUM_SIZE)
        self.resize(*DEFAULT_SIZE)
        if not safe:
            screen = QApplication.primaryScreen().availableGeometry()
            self.resize(min(DEFAULT_SIZE[0], screen.width() - 40), min(DEFAULT_SIZE[1], screen.height() - 40))

        self.mapping = MappingPage(c)
        self.general = GeneralPage(c)
        self.voice_page = VoicePage(c)
        self.pages = [self.mapping, self.voice_page, self.general]
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        mod = "⌘" if QApplication.platformName() == "cocoa" else "Ctrl+"
        self.sidebar = Sidebar(c, [(p.title, f"{mod}{i + 1}") for i, p in enumerate(self.pages)])
        self.sidebar.page_requested.connect(self.show_page)
        self.sidebar.retry_requested.connect(self.general.retry)
        self.sidebar.settings_requested.connect(self.show_general)
        self.inspector.voice_settings_requested.connect(lambda: self.show_page(self.pages.index(self.voice_page)))
        self.inspector.voice_editor.microphone_setup_requested.connect(self.show_microphone_setup)
        shell.addWidget(self.sidebar)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        shell.addWidget(workspace, 1)
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(24, 20, 24, 8)
        layout.setSpacing(10)
        header = QHBoxLayout()
        headings = QVBoxLayout()
        headings.setSpacing(3)
        self.page_title = label("", "title")
        self.page_subtitle = label("", "muted")
        headings.addWidget(self.page_title)
        headings.addWidget(self.page_subtitle)
        header.addLayout(headings, 1)
        self.learning_banner = QLabel("学习模式：按一下遥控器上要绑定的实体键")
        self.learning_banner.setObjectName("banner")
        self.learning_banner.hide()
        header.addWidget(self.learning_banner, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)
        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(scroll(page))
        layout.addWidget(self.stack, 1)
        self.feedback = QLabel("选择遥控器上的可配置按键，为它分配动作。")
        self.feedback.setObjectName("feedback")
        self.feedback.setWordWrap(True)
        self.feedback.setMinimumHeight(28)
        self.undo_button = button("撤销", c.undo_action, "link")
        feedback_row = QHBoxLayout()
        feedback_row.setContentsMargins(0, 0, 0, 0)
        feedback_row.addWidget(self.feedback, 1)
        feedback_row.addWidget(self.undo_button)
        layout.addLayout(feedback_row)

        for i in range(len(self.pages)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, lambda i=i: self.show_page(i))
        c.message.connect(self.show_message)
        c.physical_key.connect(self.show_physical_key)
        c.learning_changed.connect(self.learning_banner.setVisible)
        c.device_changed.connect(self.update_tray)
        c.mapping_changed.connect(self.update_undo)
        c.profiles_changed.connect(self.update_undo)
        self.update_undo()
        self.show_page(0)
        self.canvas.setFocus()

        if not safe and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(tray_icon(), self)
            menu = QMenu(self)
            menu.addAction("打开 " + APP_NAME, self.showNormal)
            menu.addAction("通用设置", self.show_general)
            self.add_permission_actions(menu.addMenu("权限设置"))
            menu.addAction("重新运行新手引导…", self.open_onboarding)
            if sys.platform == "darwin":
                menu.addAction("检查更新…", self.check_updates_manual)
            menu.addAction("停止语音", c.stop_voice)
            if sys.platform == "darwin":
                menu.addAction("卸载 " + APP_NAME + "…", self.uninstall_app)
            menu.addAction("退出", self.quit_app)
            self.tray.setContextMenu(menu)
            self.tray.setToolTip(APP_NAME)
            self.tray.activated.connect(
                lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
            self.tray.show()
        c.update_found.connect(self.offer_update)
        c.update_none.connect(self.updates_up_to_date)
        c.update_error.connect(self.update_failed)
        c.update_downloaded.connect(self.install_downloaded_update)
        if not safe:
            c.start()
            # First run: explain the reader component before the user sees errors.
            QTimer.singleShot(600, self.show_onboarding_once)
            if sys.platform == "darwin":
                QTimer.singleShot(8000, self.check_updates_quiet)
        if c.load_error:
            c.fail(c.load_error)

    # -- convenience accessors (tests, key_survey parity) ----------------------

    @property
    def canvas(self):
        return self.mapping.canvas

    @property
    def inspector(self):
        return self.mapping.inspector


    # -- shell -------------------------------------------------------------------

    def show_page(self, index):
        self.stack.setCurrentIndex(index)
        page = self.pages[index]
        self.page_title.setText(page.title)
        self.page_subtitle.setText(page.subtitle)
        self.sidebar.set_page(index)
        if hasattr(page, "on_show"):
            page.on_show()

    # -- updates ---------------------------------------------------------------

    def check_updates_quiet(self):
        import time
        try:
            last = float(self.controller.settings.get("last_update_check", "0"))
        except ValueError:
            last = 0
        if time.time() - last < 24 * 3600:
            return
        self.manual_update_check = False
        self.controller.check_updates()

    def check_updates_manual(self):
        self.manual_update_check = True
        self.controller.tell("正在检查更新…")
        self.controller.check_updates(manual=True)

    def updates_up_to_date(self):
        import time
        self.controller.settings["last_update_check"] = str(int(time.time()))
        self.controller.save()
        if getattr(self, "manual_update_check", False):
            self.controller.tell("已经是最新版本。")

    def update_failed(self, text):
        if getattr(self, "manual_update_check", False):
            self.controller.fail(text)

    def offer_update(self, update):
        import time
        version, _ = self.controller.local_version()
        self.controller.settings["last_update_check"] = str(int(time.time()))
        self.controller.save()
        if self.controller.settings.get("update_offered") == update.version:
            return
        notes = update.notes.strip()
        answer = QMessageBox.question(
            self, "发现新版本",
            f"发现新版本 {update.version}（当前 {version}）。" + (f"\n\n{notes}\n\n" if notes else "\n\n")
            + "现在下载并安装？安装时会退出应用，完成后自动重新打开。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        self.controller.settings["update_offered"] = update.version
        self.controller.save()
        if answer == QMessageBox.StandardButton.Yes:
            self.pending_update = update
            self.controller.tell("正在下载更新，完成后会自动重启应用。")
            self.controller.download_update(update)

    def install_downloaded_update(self, archive):
        import os, subprocess, tempfile
        from pathlib import Path
        from .. import updates
        try:
            updates_root = Path.home() / "Library/Caches/RemoteHub/updates"
            updates_root.mkdir(parents=True, exist_ok=True)
            workdir = Path(tempfile.mkdtemp(prefix="staged-", dir=updates_root))
            app = updates.stage_update(Path(archive), workdir)
            updates.verify_app(app, updates.CERTIFICATE_SHA1)
            script = Path(tempfile.mkdtemp(prefix="rh-updater-")) / "install.sh"
            script.write_text(updates.install_script(
                app.resolve(), Path("/Applications/10RemoteHub.app"), os.getpid(),
                workdir / "previous.app"))
            script.chmod(0o755)
            subprocess.Popen(["/bin/sh", str(script)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            self.controller.fail("安装更新失败：" + str(exc))
            return
        self.quit_app()

    def show_onboarding_once(self):
        if self.controller.onboarding_needed():
            self.open_onboarding()

    def open_onboarding(self):
        from .onboarding import OnboardingDialog
        dialog = OnboardingDialog(self.controller, self)
        dialog.open_mapping.connect(lambda: self.show_page(0))
        dialog.open_voice.connect(lambda: self.show_page(self.pages.index(self.voice_page)))
        dialog.open_settings.connect(self.show_general)
        self.onboarding = dialog
        try:
            dialog.exec()
        finally:
            self.onboarding = None

    def show_general(self):
        self.show_page(self.pages.index(self.general))
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_microphone_setup(self):
        self.show_page(self.pages.index(self.voice_page))
        area = self.stack.currentWidget()
        target = self.voice_page.microphone_setup
        # Let the newly visible page finish layout before scrolling to its action.
        QTimer.singleShot(0, lambda: area.ensureWidgetVisible(target, 0, 50))
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def add_permission_actions(self, menu):
        if sys.platform == "darwin":
            menu.addAction("辅助功能授权…", lambda: self.controller.open_permission("accessibility"))
        menu.addAction("查看权限与连接状态…", self.show_general)

    def show_physical_key(self, trigger, down):
        if not down or getattr(self, "onboarding", None) is not None:
            return
        button = next((b for b in self.controller.profile.buttons if b.trigger == trigger), None)
        if button is None:
            return
        unconfigured = all(action.kind == "none" for action in
                           (button.action, button.double_action, button.long_action))
        self.controller.tell(f"已收到「{button.name}」按键" + ("，未配置动作" if unconfigured else ""))

    def show_message(self, text, error):
        self.feedback.setProperty("error", bool(error))
        self.feedback.style().unpolish(self.feedback)
        self.feedback.style().polish(self.feedback)
        self.feedback.setText(text)

    def update_undo(self):
        state = self.controller.action_undo
        self.undo_button.setVisible(bool(state and state[0] == self.controller.profile.id))

    def update_tray(self):
        if self.tray:
            self.tray.setToolTip(APP_NAME + " · " + self.controller.device_view().title)

    def shutdown(self):
        self.general.close_permission_overlay()
        self.controller.shutdown()
        if self.tray:
            self.tray.hide()

    def uninstall_app(self):
        """Quit first, then let Installer remove the App and its system pieces."""
        from PySide6.QtWidgets import QMessageBox
        from ..devices import resources
        from ..installers import open_package
        package = resources() / "components" / "RemoteHub-Uninstall.pkg"
        if not package.is_file():
            self.controller.fail("当前版本没有附带卸载程序，请从发布页下载卸载包。")
            return
        answer = QMessageBox.question(
            self, APP_NAME,
            "将退出 " + APP_NAME + " 并打开卸载程序。\n\n"
            "按键映射和语音设置会保留。卸载会删除主程序、后台采集组件和虚拟麦克风。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            open_package(package)
        except Exception as exc:
            self.controller.fail("无法打开卸载程序：" + str(exc))
            return
        # Installer refuses to run while the App is open; exit right after it starts.
        QTimer.singleShot(800, self.quit_app)

    def quit_app(self):
        self.shutdown()
        QApplication.quit()

    def showNormal(self):
        set_dock_visible(True)
        super().showNormal()

    def hide_to_tray(self):
        self.hide()
        set_dock_visible(False)

    def closeEvent(self, event):
        if self.tray and not self.controller.shutting_down:
            self.hide_to_tray()
            event.ignore()
        else:
            self.shutdown()
            event.accept()
