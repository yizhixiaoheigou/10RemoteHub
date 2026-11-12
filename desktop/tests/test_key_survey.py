import json
from PySide6.QtCore import Qt
from remotehub.key_survey import Evidence,SurveyWindow


def key(value,usage=30,interface=0):
    return {"type":"value","interface":interface,"page":7,"usage":usage,"value":value,"report_id":1}


def test_survey_requires_paired_down_up_and_ignores_initial_release():
    sample=Evidence(); sample.feed(key(0)); assert not sample.complete
    sample.feed(key(1)); sample.feed(key(1)); assert not sample.complete
    sample.feed(key(0)); assert sample.complete
    assert sample.result()["triggers"]==["hid:7:30"]


def test_survey_retains_raw_and_ambiguous_multi_key_evidence():
    sample=Evidence(); sample.feed({"type":"report","hex":"018203","interface":3})
    assert not sample.complete and sample.result()["raw_reports"]==1
    for usage in (30,31):sample.feed(key(1,usage)); sample.feed(key(0,usage))
    assert not sample.complete and len(sample.result()["triggers"])==2


def test_survey_does_not_advance_while_another_interface_is_down():
    sample=Evidence(); sample.feed(key(1)); sample.feed(key(1,interface=1)); sample.feed(key(0))
    assert not sample.complete
    sample.feed(key(0,interface=1)); assert sample.complete


def test_array_marker_is_not_mistaken_for_a_second_key():
    sample=Evidence()
    sample.feed(key(30,usage=0xffffffff)); sample.feed(key(1)); sample.feed(key(0,usage=0xffffffff)); sample.feed(key(0))
    assert sample.complete and sample.result()["triggers"]==["hid:7:30"]


def test_survey_guided_round_preserves_collision_and_no_signal(qtbot,tmp_path):
    window=SurveyWindow(tmp_path/"capture",smoke=True); qtbot.addWidget(window)
    window.select(0)
    window.receive({"type":"ready","ok":True,"interfaces":4})
    window.receive(key(1)); window.auto_next(); assert window.index==0
    window.receive(key(0)); window.auto_next(); assert window.index==1
    window.receive(key(1)); window.receive(key(0)); window.auto_next()
    assert window.index==1 and "相同" in window.status.text()
    window.manual_next(); assert window.index==2
    window.manual_next(); assert window.index==3
    window.close()
    summary=json.loads((tmp_path/"capture/summary.json").read_text())
    assert summary["results"]["tv-settings"]["triggers"]==["hid:7:30"]
    assert summary["results"]["tv-up"]["reason"]=="no_signal"
    assert not list(tmp_path.rglob("profiles.json"))
    raw=[json.loads(line) for line in (tmp_path/"capture/events.jsonl").read_text().splitlines()]
    assert any(e["type"]=="value" and e["button"]=="tv-settings" for e in raw)


def test_survey_pause_keeps_incomplete_press_without_inventing_release(qtbot,tmp_path):
    window=SurveyWindow(tmp_path/"capture",smoke=True); qtbot.addWidget(window)
    window.select(0)
    window.receive({"type":"ready","ok":True,"interfaces":4}); window.receive(key(1))
    window.manual_next(); assert window.index==0
    window.stop_capture(); window.close()
    summary=json.loads((tmp_path/"capture/summary.json").read_text())
    assert summary["attempts"][0]["held"]==[[0,"hid:7:30"]]
    assert not summary["attempts"][0]["paired"]


def test_survey_permission_failure_disables_capture_and_keeps_specific_hint(qtbot,tmp_path):
    window=SurveyWindow(tmp_path/"capture",smoke=True); qtbot.addWidget(window)
    window.receive({"type":"ready","ok":False,"interfaces":3,"permission_denied":True})
    window.finished(5)
    assert not window.next.isEnabled() and "输入监控" in window.status.text()
    window.close()


def test_passive_remote_keys_cannot_change_the_survey_step(qtbot,tmp_path):
    window=SurveyWindow(tmp_path/"capture",smoke=True); qtbot.addWidget(window); window.show()
    assert window.index==0 and len(window.profile.buttons)==28
    assert window.profile.buttons[0].id=="tv-settings" and "1 / 28" in window.heading.text()
    assert "tv-power" not in window.canvas.callouts and "tv-tv" not in window.canvas.callouts
    for button in window.canvas.blocked:
        assert window.canvas.hit_test(window.canvas.hotspot_rect(button).center()) is None
        window.select_id(button.id)
        assert window.index==0
    window.receive({"type":"ready","ok":True,"interfaces":4})
    window.next.setFocus(); qtbot.keyClick(window.next,Qt.Key.Key_Space)
    window.canvas.setFocus(); qtbot.keyClick(window.canvas,Qt.Key.Key_Right)
    assert window.index==0
    window.close()


def test_disconnect_keeps_current_signal_saveable(qtbot,tmp_path):
    window=SurveyWindow(tmp_path/"capture",smoke=True,only="tv-volume-up"); qtbot.addWidget(window)
    window.receive({"type":"ready","ok":True,"interfaces":4})
    window.receive(key(1)); window.receive(key(0)); window.receive({"type":"removed"})
    assert not window.ready and window.next.isEnabled()
    window.manual_next()
    assert window.results["tv-volume-up"]["triggers"]==["hid:7:30"]
    assert len(window.profile.buttons)==1
    window.close()
