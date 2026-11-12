"""Developer-only guided survey of this remote; never writes user mappings.

Run through 脚本/采集遥控器按键.command on macOS. Raw evidence is kept in
artifacts/key-survey/<session>/ for review before building a fixed key table.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
import uuid

from PySide6.QtCore import QEvent,QProcess,QTimer,Qt
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QScrollArea,QPlainTextEdit
from .canvas import RemoteCanvas
from .icons import configure_application
from .inventory import USBMonitor
from .model import atomic_write
from .photo_template import television_profile
from .theme import apply_theme

ROOT=Path(__file__).resolve().parents[2]


class SurveyCanvas(RemoteCanvas):
    def __init__(self,results):
        self.results=results; super().__init__()
        self.blocked=[b for b in television_profile().buttons if b.id in ("tv-power","tv-tv")]
        self.blocked_labels={b.id:QLabel("不能设置",self) for b in self.blocked}
        for label in self.blocked_labels.values():
            label.setProperty("role","muted"); label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def survey_state(self,button):
        result=self.results.get(button.id)
        return "未测 / 跳过" if result and result["reason"]=="user_deferred" else "已采集" if result and result["paired"] else "待核对" if result else "待采集"

    def label_text(self,button):
        return button.name+"  ·  "+self.survey_state(button)

    def layout_callouts(self):
        super().layout_callouts()
        if not self.profile:return
        for button in self.profile.buttons:
            label=self.callouts[button.id]
            label.setToolTip("点击重新采集【"+button.name+"】")
            label.setAccessibleName(button.name+"，"+self.survey_state(button))
        for button in self.blocked:
            rect=self.hotspot_rect(button); label=self.blocked_labels[button.id]
            x=rect.left()-90 if button.id=="tv-power" else rect.right()+10
            label.setGeometry(round(x),round(rect.center().y()-14),80,28); label.show()


class Evidence:
    """Only paired HID downs/ups suggest a key; raw-only reports stay pending."""
    def __init__(self):
        self.events=[]; self.held=set(); self.triggers=set(); self.released=set()

    def feed(self,event):
        self.events.append(event)
        if event.get("type")!="value":return False
        page,usage=event["page"],event["usage"]
        # 0xffffffff is an array element marker, not a physical usage. The
        # receiver reports it alongside the actual key (and signed raw data).
        if page not in (7,9,12) or not 0<usage<=0xffff or (page==7 and usage<4):return False
        trigger=f"hid:{page}:{usage}"; key=(event["interface"],trigger)
        if event["value"]:
            self.held.add(key); self.triggers.add(trigger)
        elif key in self.held:
            self.held.remove(key); self.released.add(trigger)
        return True

    @property
    def complete(self):
        return len(self.triggers)==1 and self.triggers==self.released and not self.held

    def result(self):
        return {"triggers":sorted(self.triggers),"released":sorted(self.released),
            "held":[list(k) for k in sorted(self.held)],"paired":self.complete,
            "raw_reports":sum(e.get("type")=="report" for e in self.events)}


class SurveyWindow(QMainWindow):
    def __init__(self,output,*,smoke=False,only=None):
        super().__init__(); self.output=Path(output); self.output.mkdir(parents=True,exist_ok=False)
        self.raw=(self.output/"events.jsonl").open("a",encoding="utf-8")
        self.summary={"schema":1,"purpose":"development survey, not an approved keymap","platform":sys.platform,
            "started":datetime.now(timezone.utc).isoformat(),"vendor":0x0416,"product":0x0602,"attempts":[],"status":"waiting",
            "excluded_buttons":["tv-power","tv-tv"],
            "notes":{"tv-power":"按用户要求不可设置，不参与采集。","tv-tv":"按用户要求不可设置，不参与采集。"}}
        self.profile=television_profile(); self.index=0; self.evidence=Evidence(); self.results={}
        self.profile.buttons=[b for b in self.profile.buttons if b.id not in self.summary["excluded_buttons"]]
        if only:
            self.profile.buttons=[b for b in self.profile.buttons if b.id==only]
            if not self.profile.buttons:raise ValueError("本键不可采集或名称不存在")
        self.summary["requested_buttons"]=[b.id for b in self.profile.buttons]
        self.ready=False; self.closed=False; self.pending=b""; self.process=None; self.smoke=smoke; self.connection_error=""
        self.setWindowTitle("10RemoteHub · 临时按键采集"); self.resize(1150,820); self.setMinimumSize(1020,720)
        apply_theme(self); center=QWidget(); self.setCentralWidget(center)
        layout=QVBoxLayout(center); layout.setContentsMargins(24,20,24,20); layout.setSpacing(12)
        self.heading=QLabel("准备读取接收器"); self.heading.setProperty("role","title"); layout.addWidget(self.heading)
        intro=QLabel("电源和 TV 不能设置，已排除。"+("这轮只补采当前这一键，不改动此前记录。" if only else "共 28 键，从“设置”开始。")+"只按高亮键，松开后等提示。")
        intro.setWordWrap(True); layout.addWidget(intro)
        body=QHBoxLayout(); layout.addLayout(body,1)
        self.canvas=SurveyCanvas(self.results); scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self.canvas)
        body.addWidget(scroll,3); side=QVBoxLayout(); body.addLayout(side,2)
        self.status=QLabel("正在连接；现在先不要按键。"); self.status.setWordWrap(True); self.status.setMinimumHeight(70); side.addWidget(self.status)
        self.detail=QLabel("这次只采集信号，不执行映射动作，也不录音。"); self.detail.setWordWrap(True); side.addWidget(self.detail)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(120)
        self.log.setAccessibleName("当前按键收到的信号"); side.addWidget(self.log,1)
        self.redo=QPushButton("本键重录"); self.redo.clicked.connect(lambda:self.select(self.index)); side.addWidget(self.redo)
        self.next=QPushButton("保存当前信号 / 无信号，继续下一键"); self.next.clicked.connect(self.manual_next); side.addWidget(self.next)
        self.pause=QPushButton("暂停采集"); self.pause.clicked.connect(self.stop_capture); side.addWidget(self.pause)
        self.restart=QPushButton("重新连接并继续"); self.restart.clicked.connect(self.connect_receiver); side.addWidget(self.restart)
        foot=QLabel("每一步自动保存；关闭窗口即释放接收器。采集结果："+str(self.output)); foot.setWordWrap(True)
        foot.setTextFormat(Qt.TextFormat.PlainText); foot.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(foot)
        self.advance=QTimer(self); self.advance.setSingleShot(True); self.advance.setInterval(1300); self.advance.timeout.connect(self.auto_next)
        self.no_signal=QTimer(self); self.no_signal.setSingleShot(True); self.no_signal.setInterval(8000); self.no_signal.timeout.connect(self.waiting_hint)
        self.monitor=USBMonitor(self); self.monitor.changed.connect(self.inventory_ready)
        self.canvas.selected.connect(self.select_id)
        QApplication.instance().installEventFilter(self)
        self.select(0); self.save()
        if not smoke:QTimer.singleShot(100,self.connect_receiver)

    def select_id(self,ident):
        index=next((i for i,b in enumerate(self.profile.buttons) if b.id==ident),None)
        if index is not None:self.select(index)

    def eventFilter(self,obj,event):
        # Passive receiver reads also reach this foreground window. Do not let
        # a remote arrow/Enter/Space change the selected step or click a button.
        # This filter affects only this diagnostic Qt application, not macOS.
        if self.ready and event.type() in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease,QEvent.Type.ShortcutOverride):
            event.accept(); return True
        return super().eventFilter(obj,event)

    def save(self):
        self.summary["current_button"]=self.profile.buttons[self.index].id
        self.summary["results"]=self.results
        atomic_write(self.output/"summary.json",json.dumps(self.summary,ensure_ascii=False,indent=2))

    def record(self,event):
        event={**event,"time":time.time(),"button":self.profile.buttons[self.index].id}
        self.raw.write(json.dumps(event,ensure_ascii=False)+"\n"); self.raw.flush()

    def select(self,index):
        if self.evidence.held:
            self.status.setText("还有按键信号未松开，请先松手；若一直不恢复，点暂停后重新连接。"); return
        self.advance.stop(); self.no_signal.stop()
        if self.evidence.events:self.archive("reselected")
        self.index=index; self.evidence=Evidence(); self.log.clear()
        self.record({"type":"step"}); self.canvas.set_profile(self.profile,self.profile.buttons[index].id)
        self.heading.setText(f"{index+1} / {len(self.profile.buttons)}　请按【{self.profile.buttons[index].name}】")
        self.status.setText("正在等你按一下，再松开。" if self.ready else "监听尚未就绪，现在先不要按键。")
        self.controls(); self.save()
        if self.ready:self.no_signal.start()

    def controls(self):
        self.next.setEnabled(self.ready or bool(self.evidence.events)); self.redo.setEnabled(self.ready); self.pause.setEnabled(self.ready)
        self.restart.setEnabled(not self.ready and self.process is None)

    def connect_receiver(self):
        if self.process is not None:return
        self.connection_error=""
        self.status.setText("正在核对 USB 接收器…"); self.restart.setEnabled(False); self.monitor.refresh()

    def inventory_ready(self):
        if self.closed or self.process is not None:return
        devices=[d for d in self.monitor.devices if d.supported]
        if self.monitor.error or len(devices)!=1 or not devices[0].serial:
            self.status.setText("需要连接唯一一只带序列号的适配接收器。"+self.monitor.error); self.controls(); return
        device=devices[0]; self.summary["serial"]=device.serial; self.summary["connection"]=device.connection
        self.detail.setText("0416:0602 · "+device.serial+"\n只读采集：请保持本窗口在前台。原按键仍可能生效，例如调节系统音量。")
        self.process=QProcess(self); self.process.readyReadStandardOutput.connect(self.read_events)
        self.process.readyReadStandardError.connect(self.read_error); self.process.finished.connect(self.finished)
        self.process.start(str(ROOT/"artifacts/key_survey"),[device.serial])
        if not self.process.waitForStarted(3000):self.stop_capture(); self.status.setText("采集组件启动失败，请重新运行采集入口。"); return
        self.save()

    def read_error(self):
        if self.process:
            message=bytes(self.process.readAllStandardError()).decode(errors="replace").strip()
            if message:self.record({"type":"error","message":message}); self.log.appendPlainText(message)

    def read_events(self):
        if not self.process:return
        self.pending+=bytes(self.process.readAllStandardOutput())
        while b"\n" in self.pending:
            line,self.pending=self.pending.split(b"\n",1)
            try:self.receive(json.loads(line))
            except (ValueError,KeyError) as exc:self.record({"type":"parse_error","message":str(exc)})

    def receive(self,event):
        self.record(event)
        if event["type"]=="ready":
            self.ready=bool(event["ok"]); self.summary["status"]="listening" if self.ready else "connection_failed"
            if event.get("permission_denied"):
                self.connection_error="macOS 拒绝键盘接口：请在系统设置 → 隐私与安全性 → 输入监控中允许终端 Terminal，再重新连接。"
            elif not self.ready:self.connection_error="接收器未能完整接入；先退出其他接收工具，再重新连接。"
            self.status.setText("已就绪，请按高亮键，然后松开。" if self.ready else self.connection_error)
            self.controls(); self.save()
            if self.ready:self.no_signal.start(); self.raise_(); self.activateWindow(); self.log.setFocus()
            return
        if event["type"]=="removed":self.stop_capture(); self.status.setText("接收器已拔出，已保存本轮记录。"); return
        if not self.ready:return
        changed=self.evidence.feed(event)
        if event["type"] in ("report","value"):
            self.log.appendPlainText(json.dumps(event,ensure_ascii=False))
        if changed:
            self.advance.stop()
            if self.evidence.complete:
                self.status.setText("已收到按下和松开。稍候，自动提示下一个键。")
                self.advance.start()
            else:self.status.setText("已收到信号，请松开；多个键码会保留供核对。")

    def waiting_hint(self):
        if self.ready and not self.evidence.complete:
            self.status.setText("还没有完整的按下/松开信号。可再按一次；仍没反应就点“继续下一键”。未收到不等于确定为红外键。")

    def archive(self,reason):
        result={"button_id":self.profile.buttons[self.index].id,"name":self.profile.buttons[self.index].name,
            "reason":reason,**self.evidence.result()}
        self.summary["attempts"].append(result)
        self.record({"type":"attempt",**result}); return result

    def auto_next(self):
        if not self.ready or not self.evidence.complete:return
        trigger=next(iter(self.evidence.triggers))
        other=[v["name"] for k,v in self.results.items() if k!=self.profile.buttons[self.index].id and trigger in v["triggers"]]
        if other:
            self.status.setText("本键与【"+"、".join(other)+"】信号相同。可重录，或点继续保留结果供核对。"); return
        self.finish_step("paired")

    def manual_next(self):
        if self.ready or self.evidence.events:self.finish_step("manual_review" if self.evidence.events else "no_signal")

    def finish_step(self,reason):
        if self.evidence.held:
            self.status.setText("按键仍显示按下。请松开；一直不恢复时暂停并重新连接，记录会保留。"); return
        self.advance.stop(); self.no_signal.stop()
        self.results[self.profile.buttons[self.index].id]=self.archive(reason)
        self.evidence=Evidence(); self.save()
        if self.index+1<len(self.profile.buttons):self.select(self.index+1)
        else:
            self.stop_capture(); self.summary["status"]="round_finished"; self.save()
            self.heading.setText(f"本轮 {len(self.profile.buttons)} 键采集已结束（电源、TV 不参与）")
            self.status.setText("结果已保存，接收器已释放。接下来核对原始信号，再固化进此遥控器模板。")

    def finished(self,code,*args):
        self.ready=False; self.advance.stop(); self.no_signal.stop()
        if self.process:self.process.deleteLater(); self.process=None
        if not self.closed:
            self.controls()
            if code:self.status.setText(self.connection_error or "监听未能继续。记录已保存；请查看下方错误，检查是否有其他接收工具或输入监控权限问题。")

    def stop_capture(self):
        if self.closed:return
        self.ready=False; self.advance.stop(); self.no_signal.stop()
        if self.process:
            self.process.terminate()
            if not self.process.waitForFinished(2000):self.process.kill(); self.process.waitForFinished(1000)
        if self.evidence.events:self.archive("paused")
        # Keep the captured step available for Save/Next after a disconnect.
        # Never erase a voice-key packet simply because its receiver reappears.
        self.pending=b""; self.summary["status"]="paused"
        self.controls(); self.save(); self.status.setText("已暂停并释放接收器，记录已保存。")

    def closeEvent(self,event):
        if self.closed:event.accept(); return
        self.stop_capture(); self.closed=True; self.monitor.stop(); self.raw.close(); event.accept()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--smoke",action="store_true"); parser.add_argument("--output",type=Path); parser.add_argument("--screenshot",type=Path)
    parser.add_argument("--only",choices=[b.id for b in television_profile().buttons if b.configurable])
    args=parser.parse_args()
    if sys.platform!="darwin" and not args.smoke:raise SystemExit("This survey captures macOS HID reports only.")
    output=args.output or ROOT/"artifacts/key-survey"/(datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6])
    app=QApplication(sys.argv); app.setApplicationName("10RemoteHub 按键采集"); configure_application(app,native=not args.smoke)
    window=SurveyWindow(output,smoke=args.smoke,only=args.only); window.show()
    if args.smoke:
        def done():
            if args.screenshot:window.grab().save(str(args.screenshot))
            window.close()
        QTimer.singleShot(400,done)
    return app.exec()

if __name__=="__main__":raise SystemExit(main())
