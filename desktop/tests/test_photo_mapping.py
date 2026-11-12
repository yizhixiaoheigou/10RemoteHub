"""UI interactions never execute an assigned action while editing the photo."""
from PySide6.QtCore import Qt
from remotehub.ui import MainWindow
from remotehub.model import Action
import pytest


def test_all_pages_fit_minimum_window_without_horizontal_clipping(qtbot, tmp_path):
    from PySide6.QtWidgets import QScrollArea
    window = MainWindow(tmp_path, safe=True)
    qtbot.addWidget(window)
    window.resize(1200, 720)
    window.show()
    for index in range(len(window.pages)):
        window.show_page(index)
        qtbot.wait(20)
        for area in window.findChildren(QScrollArea):
            if area.isVisible():
                assert area.horizontalScrollBar().maximum() == 0
                assert area.widget().width() <= area.viewport().width()
    window.shutdown()


def test_photo_key_label_and_keyboard_select_same_model(qtbot,tmp_path,monkeypatch):
    window=MainWindow(tmp_path,safe=True); qtbot.addWidget(window); window.show(); c=window.controller
    calls=[]; monkeypatch.setattr(c.runner,"run",lambda *args:calls.append(args))
    canvas=window.canvas
    # Every center is its own target, especially the five directional keys.
    for key in c.profile.buttons:
        assert canvas.hit_test(canvas.hotspot_rect(key).center())==(key.id if key.configurable else None)
    key=next(b for b in c.profile.buttons if b.name=="1")
    qtbot.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=canvas.hotspot_rect(key).center().toPoint())
    assert c.selected.id==key.id and canvas.callouts[key.id].isChecked()
    second=next(b for b in c.profile.buttons if b.name=="2")
    qtbot.mouseClick(canvas.callouts[second.id],Qt.MouseButton.LeftButton)
    assert c.selected.id==second.id and window.inspector.title.text()=="2"
    assert canvas.callouts[second.id].isChecked() and not canvas.callouts[key.id].isChecked()
    # Clicking a leader line away from both ends selects its key.
    qtbot.mouseClick(canvas.callouts[key.id],Qt.MouseButton.LeftButton)
    # Use the part of the line between the photo and the label; where a line
    # crosses another key's hotspot, the hotspot wins (by design).
    line=canvas.lines[second.id]
    point=next(line.pointAtPercent(t/40) for t in range(40,0,-1)
               if not any(canvas.hotspot_rect(b).contains(line.pointAtPercent(t/40)) for b in c.profile.buttons)
               and not any(l.geometry().contains(line.pointAtPercent(t/40).toPoint()) for l in canvas.callouts.values()))
    qtbot.mouseClick(canvas,Qt.MouseButton.LeftButton,pos=point.toPoint())
    assert c.selected.id==second.id
    # Physical arrow keys must not move the selection: macOS seizes the device,
    # and on Windows the same key would otherwise act twice (navigate + mapping).
    canvas.setFocus(); qtbot.keyClick(canvas,Qt.Key.Key_Right)
    assert c.selected.id==second.id
    assert calls==[] and not c.enabled
    window.shutdown()


def test_saved_assignment_updates_callout_and_survives_resize(qtbot,tmp_path):
    window=MainWindow(tmp_path,safe=True); qtbot.addWidget(window); window.show(); c=window.controller
    selected=c.selected; c.assign(Action("shortcut",["ctrl","shift","a"]))
    from remotehub.presentation import key_label
    callout=window.canvas.callouts[selected.id]
    assert key_label(["ctrl","shift","a"]) in callout.toolTip() and callout.property("state")=="assigned"
    for width,height in ((1100,720),(1440,1000)):
        window.resize(width,height); qtbot.wait(30)
        canvas=window.canvas
        assert canvas.hit_test(canvas.hotspot_rect(selected).center())==selected.id
        # Every key has a label; labels stay inside the canvas, never overlap
        # each other, and never cover the photo.
        labels=[item for item in canvas.callouts.values() if item.isVisible()]
        assert all(canvas.rect().contains(item.geometry()) for item in labels)
        assert len(labels)==len(c.profile.buttons)
        photo=canvas.image_rect().toRect()
        for i,a in enumerate(labels):
            assert not a.geometry().intersects(photo)
            assert all(not a.geometry().intersects(b.geometry()) for b in labels[i+1:])
    restored=MainWindow(tmp_path,safe=True); qtbot.addWidget(restored)
    assert next(b for b in restored.controller.profile.buttons if b.id==selected.id).action==selected.action
    window.shutdown(); restored.shutdown()


def test_inspector_only_shows_relevant_fields_and_drafts_do_not_save(qtbot,tmp_path,monkeypatch):
    window=MainWindow(tmp_path,safe=True); qtbot.addWidget(window); window.show()
    c=window.controller; ins=window.inspector
    ins.choose_kind("shortcut")
    assert ins.sequence.isVisible() and not ins.file_target.isVisible()
    assert c.selected.action.kind=="none"  # recording nothing saves nothing
    ins.choose_kind("file")
    assert not ins.sequence.isVisible() and ins.file_target.isVisible() and ins.file_app.isVisible()
    ins.choose_kind("close_window")  # no value needed: saved on click
    assert not ins.file_target.isVisible() and not ins.sequence.isVisible()
    assert c.selected.action.kind=="close_window"
    ins.choose_kind("toggle_app")
    assert ins.app_target.isVisible() and c.selected.action.kind=="close_window"
    assert "原动作保留" in ins.summary.text()
    first=c.selected.id
    c.select(next(b.id for b in c.configurable_buttons() if b.id!=first))
    c.select(first)
    assert ins.draft_kind is None and ins.kinds["close_window"].isChecked()
    window.shutdown()


def test_inspector_commits_complete_values(qtbot,tmp_path,monkeypatch):
    from remotehub.ui import inspector as module
    from PySide6.QtGui import QKeySequence
    window=MainWindow(tmp_path,safe=True); qtbot.addWidget(window); window.show()
    c=window.controller; ins=window.inspector
    app=tmp_path/"Editor.app"; app.mkdir(); doc=tmp_path/"plan.pdf"; doc.write_text("x")
    monkeypatch.setattr(module,"choose_application",lambda parent:str(app))
    monkeypatch.setattr(module,"choose_file",lambda parent:str(doc))
    ins.choose_kind("toggle_app"); ins.pick_app()
    assert c.selected.action==Action("toggle_app",target=str(app))
    c.assign(Action("app",target=str(app)))  # legacy open-only config
    assert ins.app_target.isVisible() and "旧配置" in ins.hint.text()
    ins.choose_kind("toggle_app")  # same target carries over
    assert c.selected.action==Action("toggle_app",target=str(app))
    ins.choose_kind("file"); ins.pick_file_app()
    assert c.selected.action.kind=="toggle_app" and "Editor" in ins.file_app.text()
    ins.pick_file()
    assert c.selected.action.kind=="file" and c.selected.action.application==str(app)
    ins.choose_kind("shortcut")
    ins.sequence.setKeySequence(QKeySequence("Ctrl+Shift+K")); ins.sequence_done()
    assert c.selected.action.kind=="shortcut" and set(c.selected.action.keys)>={"shift","k"}
    ins.kinds["common:copy"].click()
    assert c.selected.action==Action("common",target="copy") and ins.kinds["common:copy"].isChecked()
    restored=MainWindow(tmp_path,safe=True); qtbot.addWidget(restored)
    assert restored.controller.profile.buttons==c.profile.buttons
    window.shutdown(); restored.shutdown()


@pytest.mark.parametrize("action", [Action("shortcut",["ctrl","a"]),Action("file",target="/example/document.pdf"),Action("voice")])
def test_clear_mapping_is_visible_preserves_key_and_persists(qtbot,tmp_path,monkeypatch,action):
    window=MainWindow(tmp_path,safe=True);qtbot.addWidget(window);window.show();c=window.controller
    key=c.selected;identity=(key.id,key.trigger,list(key.rect));count=len(c.profile.buttons)
    c.assign(action)
    calls=[];monkeypatch.setattr(c.runner,"run",lambda *args:calls.append(args))
    ins=window.inspector
    assert not ins.details.isVisible()
    assert ins.clear_current.isVisible() and ins.clear_current.isEnabled()
    qtbot.mouseClick(ins.clear_current,Qt.MouseButton.LeftButton)
    assert c.selected.id==key.id and key.action==Action()
    assert (key.id,key.trigger,key.rect)==identity and len(c.profile.buttons)==count
    assert ins.summary.text()=="单击动作：未设置"
    assert "未设置" not in window.canvas.callouts[key.id].text() and window.canvas.callouts[key.id].property("state")=="empty"
    assert window.mapping.count.text()=="已分配 0 / 27"
    assert not ins.clear_current.isEnabled()
    assert calls==[]
    restored=MainWindow(tmp_path,safe=True);qtbot.addWidget(restored)
    assert next(b for b in restored.controller.profile.buttons if b.id==key.id).action==Action()
    window.shutdown();restored.shutdown()


def test_fixed_remote_does_not_show_generic_debug_or_geometry_controls(qtbot,tmp_path):
    window=MainWindow(tmp_path,safe=True);qtbot.addWidget(window);window.show();c=window.controller;ins=window.inspector
    for kind in ("none","close_window"):
        c.assign(Action(kind))
        assert ins.test.isHidden() and ins.learn.isHidden()
        assert ins.more.isHidden() and ins.details.isHidden() and ins.details_divider.isHidden()
        assert not window.canvas.edit and not window.mapping.edit_strip.isVisible()
        assert ins.clear_current.isVisible()
        assert all(control.isVisible() for kind,control in ins.kinds.items() if kind != "voice")
        assert not ins.kinds["voice"].isVisible()
        assert "内置键码" not in ins.trigger.text()
    window.shutdown()


def test_non_fixed_profile_keeps_learning_geometry_and_test(qtbot,tmp_path,monkeypatch):
    window=MainWindow(tmp_path,safe=True);qtbot.addWidget(window);window.show();c=window.controller;ins=window.inspector
    c.profile.product=0x1234  # any unadapted model
    c.mapping_changed.emit()
    assert not ins.more.isHidden() and not ins.test.isHidden()
    c.assign(Action("shortcut",["ctrl","a"]))
    assert ins.test.isEnabled()
    ins.more.click(); assert ins.details.isVisible() and ins.learn.isVisible()
    ins.draw.setChecked(True); assert window.canvas.edit and window.mapping.edit_strip.isVisible()
    window.shutdown()
