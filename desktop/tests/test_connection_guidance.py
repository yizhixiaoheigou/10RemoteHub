"""Connection guidance uses simulated failures, never actual USB access."""
import sys
import pytest
from remotehub.inventory import USBDevice
from remotehub.ui import MainWindow


@pytest.mark.parametrize("permission,error,title", [
    ("未授权", "HID exclusive open failed: 0xe00002e2", "设备连接出错"),
    ("已授权", "HID exclusive open failed: 0xe00002c1", "设备连接出错"),
    ("无法检测", "helper startup failed", "设备连接出错"),
])
def test_async_failure_keeps_cause_and_settings_route(qtbot, tmp_path, monkeypatch, permission, error, title):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    w.show()
    c = w.controller
    monkeypatch.setattr(c, "permission_status", lambda: {"input": permission})
    monkeypatch.setattr(c.device, "start", lambda *args: None)
    c.monitor.apply([USBDevice(0x0416, 0x0602, "", "Receiver", "port")])
    c.set_enabled(True)
    c.device.failed.emit(error)
    c.device.stopped.emit(c.device.generation)
    assert c.mapping_error == error
    assert w.sidebar.status.text() == title
    assert error in w.sidebar.detail.text()
    assert w.sidebar.status.property("tone") == "error"
    assert w.sidebar.settings.isVisible()
    w.sidebar.settings.click()
    assert w.stack.currentIndex() == w.pages.index(w.general)
    assert error in w.general.connection_error.text()
    assert w.general.connection_error.isVisible()
    assert "输入监控" not in w.sidebar.detail.text()
    # A later unplug is a USB state, not the previous permission error.
    c.monitor.apply([])
    assert "未发现" in w.sidebar.status.text()
    assert "USB 接口" in w.sidebar.detail.text()
    assert not w.sidebar.settings.isVisible()
    assert w.general.connection_error.isHidden()
    assert error not in w.feedback.text()
    w.shutdown()


def test_scan_failure_does_not_stop_live_capture_or_rearm_failed_attempt(qapp, tmp_path, monkeypatch):
    from remotehub.controller import AppController
    c = AppController(tmp_path)
    calls = []
    monkeypatch.setattr(c.device, 'start', lambda *a: calls.append('start'))
    monkeypatch.setattr(c.device, 'stop', lambda: calls.append('stop'))
    receiver = USBDevice(0x0416, 0x0602, '', 'Receiver', 'port')
    c.monitor.apply([receiver])
    c.input_ready(c.device.generation)
    c.monitor.apply([], 'inventory timeout')
    assert c.enabled and c.keys_ready and calls == ['start']
    assert c.device_view().title == 'USB 检测失败'
    c.monitor.apply([receiver])
    assert calls == ['start']
    c._device_failed('transport failed')
    c._device_stopped(c.device.generation)
    c.monitor.apply([], 'inventory timeout')
    c.monitor.apply([receiver])
    assert c.mapping_attempted and calls == ['start']
    assert c.mapping_error == 'transport failed'
    c.shutdown()


def test_unplug_keeps_unrelated_action_feedback(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    c.monitor.apply([USBDevice(0x0416, 0x0602, '', 'Receiver', 'port')])
    c._device_failed('transport failed')
    c.tell('映射已保存')
    c.monitor.apply([])
    assert w.feedback.text() == '映射已保存'
    w.shutdown()


def test_collector_error_does_not_infer_input_permission(qapp, tmp_path, monkeypatch):
    from remotehub.controller import AppController
    c = AppController(tmp_path)
    monkeypatch.setattr(c, 'permission_status', lambda: pytest.fail('USB collector does not use Input Monitoring'))
    c.monitor.apply([USBDevice(0x0416, 0x0602, '', 'Receiver', 'port')])
    c._device_failed('设备采集已停止（2）')
    assert c.device_view().title == '设备连接出错'
    assert c.device_view().diagnostic == '设备采集已停止（2）'
    c.shutdown()


def test_scan_error_is_not_reported_as_permission_failure(qtbot, tmp_path):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    w.controller.monitor.apply([], "inventory failed")
    assert w.sidebar.status.text() == "USB 检测失败"
    assert "重新检测" in w.sidebar.detail.text()
    assert "inventory failed" in w.general.connection_error.text()
    w.shutdown()


def test_permission_card_keeps_buttons_and_multiline_errors_inside_layout(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLabel, QPushButton
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    monkeypatch.setattr(c, "permission_status", lambda: {"input": "未授权"})
    c.monitor.apply([USBDevice(0x0416, 0x0602, "", "Receiver", "port")])
    w.show_page(w.pages.index(w.general))
    w.show()
    for width, height, lines in ((1200, 720, 2), (1280, 840, 4), (1200, 720, 1)):
        w.resize(width, height)
        c.device.failed.emit(("HID exclusive open failed: 0xe00002e2. Keyboard seizure needs privilege "
                              "in addition to Input Monitoring.\n") * lines)
        qtbot.wait(30)
        card = w.general.connection_status.parentWidget()
        for button in card.findChildren(QPushButton):
            if button.isVisible():
                assert button.parentWidget().rect().contains(button.geometry())
        for text in card.findChildren(QLabel):
            if text.isVisible() and text.hasHeightForWidth():
                assert text.height() >= text.heightForWidth(text.width()), (lines, text.text(), card.height(), card.heightForWidth(card.width()))
        assert card.height() >= card.heightForWidth(card.width())
    w.shutdown()


@pytest.mark.skipif(sys.platform != "darwin", reason="the unified collector is macOS-only")
def test_missing_collector_is_a_state_not_an_error(qtbot, tmp_path, monkeypatch):
    """A fresh install has no collector yet; first launch must not show red errors."""
    from remotehub import mac_device_helper
    monkeypatch.setattr(mac_device_helper, 'installation_status', lambda: (1, '设备组件尚未安装，请到通用设置安装'))
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c = w.controller
    c.auto_mapping = True
    messages = []
    c.message.connect(lambda text, error: messages.append((text, error)))
    c.monitor.apply([USBDevice(0x0416, 0x0602, '', 'Receiver', 'port')])
    view = c.device_view()
    assert view.tone != 'error'
    assert '采集组件' in view.title
    assert c.helper_missing and c.mapping_attempted and not c.mapping_error
    assert not any(error for _, error in messages)
    w.shutdown()


@pytest.mark.skipif(sys.platform != 'darwin', reason='Privileged collector packages are macOS-only')
def test_device_component_actions_have_clear_hierarchy(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton, QMessageBox
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    assert w.general.helper_install.property('role') == 'primary'
    assert w.general.helper_install.text() == '安装 / 更新读取组件'
    calls = []
    monkeypatch.setattr(w.controller, 'install_collector', lambda remove=False: calls.append(remove))
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    w.general.install_helper(True)
    assert calls == []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    w.general.install_helper(True)
    assert calls == [True]
    w.shutdown()


def test_transient_usb_io_recovers_once_without_global_error(qapp, tmp_path, monkeypatch):
    from remotehub.controller import AppController
    c = AppController(tmp_path)
    starts = []
    monkeypatch.setattr(c.device, 'start', lambda *args: starts.append('start'))
    receiver = USBDevice(0x0416, 0x0602, '', 'Receiver', 'port')
    c.monitor.apply([receiver])
    c.input_ready(c.device.generation)
    c._device_failed('collector read receiver: LIBUSB_ERROR_IO (-1)')
    assert c.transient_error and not c.mapping_error
    assert c.device_view().tone == 'busy'
    c._device_stopped(c.device.generation)
    assert c.transient_error and not c.mapping_error
    c._recover_transient()
    assert starts == ['start', 'start']
    c.input_ready(c.device.generation)
    assert c.recovery_attempts == 0 and not c.transient_error
    c._device_failed('collector read receiver: LIBUSB_ERROR_IO (-1)')
    c._recover_transient()
    c._device_failed('collector read receiver: LIBUSB_ERROR_IO (-1)')
    assert 'LIBUSB_ERROR_IO' in c.mapping_error
    assert c.device_view().tone == 'error'
    c.shutdown()


def test_unmapped_physical_key_has_immediate_feedback(qtbot, tmp_path):
    from remotehub.photo_template import KEYMAP
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    trigger = KEYMAP['keys']['tv-number-2']['trigger']
    w.controller.on_key(trigger, True)
    assert '已收到「2」按键，未配置动作' in w.feedback.text()
    w.controller.on_key(trigger, False)
    w.shutdown()
