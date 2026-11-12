"""First-run guide: shows the reader install first, then permissions, then mapping."""
import sys

import pytest
from remotehub import mac_device_helper
from remotehub.controller import StatusView
from remotehub.ui import onboarding as onboarding_module
from remotehub.ui.window import MainWindow


def window(qtbot, tmp_path, monkeypatch, installed=False):
    monkeypatch.setattr(mac_device_helper, 'installation_status',
                        lambda: (0 if installed else 1, '已安装' if installed else '尚未安装'))
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    return w


def test_first_run_marks_profile_and_opens_mapping(qtbot, tmp_path, monkeypatch):
    w = window(qtbot, tmp_path, monkeypatch)
    c = w.controller
    assert c.onboarding_needed()
    dialog = onboarding_module.OnboardingDialog(c)
    qtbot.addWidget(dialog)
    assert dialog.index == 0
    dialog.next_page()
    assert dialog.index == 1
    dialog.next_page()
    assert dialog.index == 2
    opened = []
    dialog.open_mapping.connect(lambda: opened.append(True))
    dialog.next_page()
    assert opened == [True]
    assert not c.onboarding_needed()
    assert c.settings.get('onboarded') == '1'
    w.shutdown()


def test_install_button_opens_installer_and_refreshes(qtbot, tmp_path, monkeypatch):
    w = window(qtbot, tmp_path, monkeypatch)
    calls, told = [], []
    monkeypatch.setattr(w.controller, 'install_collector', lambda remove=False: calls.append(remove))
    monkeypatch.setattr(w.controller, 'tell', lambda text: told.append(text))
    dialog = onboarding_module.OnboardingDialog(w.controller)
    qtbot.addWidget(dialog)
    dialog.show_page(1)
    dialog.install_component()
    assert calls == [False] and told
    w.shutdown()


@pytest.mark.skipif(sys.platform != "darwin", reason="reader component status is macOS-only")
def test_component_status_is_read_only(qtbot, tmp_path, monkeypatch):
    w = window(qtbot, tmp_path, monkeypatch, installed=True)
    dialog = onboarding_module.OnboardingDialog(w.controller)
    qtbot.addWidget(dialog)
    dialog.refresh()
    assert dialog.component_pill.text() == '已安装'
    w.shutdown()


def test_show_onboarding_once_respects_the_saved_flag(qtbot, tmp_path, monkeypatch):
    from types import SimpleNamespace
    w = window(qtbot, tmp_path, monkeypatch)
    created = []

    class Fake:
        def __init__(self, controller, parent=None):
            created.append(controller)
            self.open_mapping = SimpleNamespace(connect=lambda slot: None)
            self.open_voice = SimpleNamespace(connect=lambda slot: None)
            self.open_settings = SimpleNamespace(connect=lambda slot: None)

        def exec(self):
            pass

    monkeypatch.setattr(onboarding_module, 'OnboardingDialog', Fake)
    w.show_onboarding_once()
    assert len(created) == 1
    w.controller.finish_onboarding()
    w.show_onboarding_once()
    assert len(created) == 1
    w.shutdown()


def test_windows_prepare_page_names_both_components_and_links_out(qtbot, tmp_path, monkeypatch):
    """Windows has no installable reader, but two third-party pieces are required."""
    from PySide6.QtWidgets import QLabel, QPushButton
    import remotehub.ui.onboarding as onboarding_module

    w = window(qtbot, tmp_path, monkeypatch)
    monkeypatch.setattr(onboarding_module.sys, "platform", "win32")
    dialog = onboarding_module.OnboardingDialog(w.controller)
    qtbot.addWidget(dialog)
    dialog.show_page(1)

    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert "Zadig" in text and "VB-CABLE" in text
    assert "Interface 3" in text and "Interface 4" in text
    buttons = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "前往通用设置" in buttons and "前往语音设置" in buttons
    w.shutdown()


def test_real_number_key_completes_first_run_verification(qtbot, tmp_path, monkeypatch):
    from remotehub.photo_template import KEYMAP

    w = window(qtbot, tmp_path, monkeypatch)
    dialog = onboarding_module.OnboardingDialog(w.controller)
    qtbot.addWidget(dialog)
    dialog.show_page(2)
    trigger = KEYMAP['keys']['tv-number-1']['trigger']
    w.controller.on_key(trigger, True)
    assert dialog.verified
    assert dialog.verify_pill.text() == '按键已验证'
    w.controller.on_key(trigger, False)
    w.shutdown()
