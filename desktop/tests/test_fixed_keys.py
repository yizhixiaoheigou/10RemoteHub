from dataclasses import asdict
import json
from PySide6.QtCore import Qt
from remotehub.model import Action
from remotehub.photo_template import KEYMAP,television_profile
from remotehub.hid_reports import HIDReports
from pathlib import Path

DESCRIPTORS=json.loads((Path(__file__).parent/"fixtures/receiver-descriptors.json").read_text())["descriptors"]
from remotehub.ui import MainWindow


def test_all_28_fixed_keys_match_captured_press_and_release_bytes():
    profile=television_profile()
    keys=[b for b in profile.buttons if b.configurable]
    assert len(keys)==28 and len({b.trigger for b in keys})==28
    for button in keys:
        evidence=KEYMAP["keys"][button.id]
        down=bytes.fromhex(evidence["press_hex"]); up=bytes.fromhex(evidence["release_hex"])
        interface = "4" if evidence["primary_page"]==1 else "1"
        decoder=HIDReports(bytes.fromhex(DESCRIPTORS[interface]))
        assert decoder.decode(down)==[(button.trigger,True)]
        assert decoder.decode(down)==[]
        assert decoder.decode(up)==[(button.trigger,False)]


def test_hash_key_is_inside_real_keyboard_descriptor_usage_range():
    decoder=HIDReports(bytes.fromhex(DESCRIPTORS["4"]))
    down=bytes.fromhex(KEYMAP["keys"]["tv-number-#"]["press_hex"])
    assert decoder.decode(down)==[("hid:7:204",True)]
    assert decoder.decode(bytes(8))==[("hid:7:204",False)]


def test_disabled_ir_keys_cannot_select_configure_or_run_legacy_actions(qtbot,tmp_path,monkeypatch):
    window=MainWindow(tmp_path,safe=True);qtbot.addWidget(window);window.show(); c=window.controller
    selected=c.selected.id; calls=[]
    monkeypatch.setattr(c.runner,"run",lambda *args:calls.append(args))
    for button in c.profile.buttons:
        if button.configurable:continue
        label=window.canvas.callouts[button.id]
        assert label.isVisible() and not label.isEnabled() and "不能设置" in label.text()
        qtbot.mouseClick(window.canvas,Qt.MouseButton.LeftButton,pos=window.canvas.hotspot_rect(button).center().toPoint())
        c.select(button.id)
        assert c.selected.id==selected
        button.trigger="hid:7:999"; button.action=Action("shortcut",["ctrl","a"])
        c.on_key(button.trigger,True);c.on_key(button.trigger,False)
    assert not calls and not window.inspector.learn.isVisible()
    assert window.mapping.count.text().endswith("/ 27")
    window.shutdown()


def test_existing_photo_gets_fixed_codes_without_losing_action_and_has_backup(qtbot,tmp_path):
    profile=television_profile()
    for button in profile.buttons:button.trigger=""
    number=next(b for b in profile.buttons if b.id=="tv-number-1")
    number.action=Action("shortcut",["ctrl","a"])
    original=json.dumps({"profiles":[asdict(profile)],"settings":{}})
    (tmp_path/"profiles.json").write_text(original)
    window=MainWindow(tmp_path,safe=True);qtbot.addWidget(window)
    restored=next(b for b in window.controller.profile.buttons if b.id==number.id)
    assert restored.trigger=="hid:7:30" and restored.action==number.action
    window.controller.save()
    assert next(tmp_path.glob("profiles-before-standalone-*.json")).read_text()==original
    window.shutdown()
