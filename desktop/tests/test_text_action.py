from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from remotehub.actions import ActionRunner, KeyOutput
from remotehub.model import Action, Button, Profile
from remotehub.presentation import action_text
from remotehub.ui import MainWindow


@pytest.mark.parametrize('text', ['CODEX', '你好，世界 🙂', '  第一行\n第二行\t末尾  '])
def test_text_profile_export_import_preserves_exact_content(text):
    profile = Profile(buttons=[Button(action=Action('text', text=text))])
    assert Profile.loads(profile.dumps()).buttons[0].action.text == text


@pytest.mark.parametrize('text', ['', None, 123, 'x' * 10001, 'a\x00b', '\x1b', '\ud800'])
def test_invalid_text_rejected_before_execution(text):
    with pytest.raises(ValueError):
        Action('text', text=text).validate()


@pytest.mark.parametrize('platform,modifier', [('darwin', 'cmd'), ('win32', 'ctrl')])
def test_text_pastes_once_without_enter_or_real_clipboard(qapp, monkeypatch, platform, modifier):
    events = []
    monkeypatch.setattr('remotehub.actions.sys.platform', platform)
    monkeypatch.setattr(QApplication, 'clipboard', staticmethod(
        lambda: SimpleNamespace(setText=lambda value: events.append(('text', value)))))
    keys = KeyOutput()
    monkeypatch.setattr(keys, 'shortcut', lambda chord: events.append(('keys', chord)))
    runner = ActionRunner(keys)
    action = Action('text', text='CODEX 中文\n$HOME; `literal`')
    assert runner.run(action, True) == '已请求输入文本'
    runner.run(action, False)
    assert events == [('text', action.text), ('keys', [modifier, 'v'])]
    keys.held = ['alt']
    with pytest.raises(RuntimeError):
        runner.run(action)
    assert len(events) == 2


def test_text_editor_save_reload_clear_and_draft_isolation(qtbot, tmp_path, monkeypatch):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c, ins = w.controller, w.inspector
    c.select('tv-number-2')
    assert c.selected.name == '2'
    first = c.selected_id
    c.assign(Action('close_window'))
    monkeypatch.setattr(c.runner, 'run', lambda *a: pytest.fail('Editing must not execute'))
    ins.choose_kind('text')
    ins.text_input.setPlainText('CODEX 中文\n第二行')
    assert c.selected.action.kind == 'close_window'
    ins.refresh()  # unrelated status refresh must not erase the draft
    assert ins.text_input.toPlainText() == 'CODEX 中文\n第二行'
    ins.text_save.click()
    assert c.selected.action == Action('text', text='CODEX 中文\n第二行')
    assert ins.draft_kind is None
    again = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(again)
    again.controller.select(first)
    assert again.controller.selected.action == c.selected.action
    ins.text_input.setPlainText('unsaved')
    other = next(b for b in c.profile.buttons if b.configurable and b.id != first and b.action.kind != 'voice')
    c.select(other.id)
    ins.choose_kind('text')
    assert ins.text_input.toPlainText() == ''
    c.select(first)
    assert ins.text_input.toPlainText() == 'CODEX 中文\n第二行'
    ins.text_input.setPlainText('x' * 10001)
    ins.text_save.click()
    assert not ins.text_error.isHidden()
    assert c.selected.action.text == 'CODEX 中文\n第二行'
    ins.clear_current.click()
    assert c.selected.action.kind == 'none'
    w.shutdown()
    again.shutdown()


def test_text_failed_save_preserves_draft_and_repeated_press_runs_once(qtbot, tmp_path, monkeypatch):
    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c, ins = w.controller, w.inspector
    c.select('tv-number-2')
    assert c.selected.name == '2'
    c.assign(Action('close_window'))
    ins.choose_kind('text')
    ins.text_input.setPlainText('CODEX')
    original_save = c.save
    monkeypatch.setattr(c, 'save', lambda: False)
    ins.text_save.click()
    assert c.selected.action.kind == 'close_window'
    assert ins.visible_kind == 'text' and ins.text_input.toPlainText() == 'CODEX'
    monkeypatch.setattr(c, 'save', original_save)
    ins.text_save.click()
    emitted = []
    monkeypatch.setattr(c.runner.keys, 'input_text', emitted.append)
    trigger = c.selected.trigger
    assert trigger
    for down in (True, True, False, True, False):
        c.on_key(trigger, down)
    assert emitted == ['CODEX', 'CODEX']
    assert len(action_text(Action('text', text='x' * 1000))) < 50
    w.shutdown()


def test_unsaved_text_guard_can_cancel_and_save(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    w = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(w)
    c, ins = w.controller, w.inspector
    first = c.selected_id
    other = next(b.id for b in c.profile.buttons if b.configurable and b.id != first)
    c.assign(Action('text', text='saved'))
    ins.text_input.setPlainText('unsaved')
    assert ins.text_dirty and ins.text_save.isEnabled()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Cancel)
    w.mapping.select_key(other)
    assert c.selected_id == first and ins.text_input.toPlainText() == 'unsaved'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Save)
    w.mapping.select_key(other)
    assert c.selected_id == other
    assert next(b for b in c.profile.buttons if b.id == first).action == Action('text', text='unsaved')
    assert not w.undo_button.isHidden()
    w.undo_button.click()
    assert next(b for b in c.profile.buttons if b.id == first).action == Action('text', text='saved')
    w.shutdown()
