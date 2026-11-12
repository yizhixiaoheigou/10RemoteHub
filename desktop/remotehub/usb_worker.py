"""Explicitly launched USB worker. Captures an attached supported receiver by VID/PID.

Runs separately from GUI; on macOS administrator authorization is required by
libusb's whole-device capture. Parent disconnect always stops/restores device.
"""
import argparse
import base64
import json
from pathlib import Path
import select
import signal
import socket
import sys
import time
from .hid_reports import HIDReports


def run(argv):
    p=argparse.ArgumentParser()
    p.add_argument("--port",type=int,required=True)
    p.add_argument("--auth-file",type=Path,required=True)
    a=p.parse_args(argv)
    if not 1024<=a.port<=65535: p.error("invalid worker port")
    token=a.auth_file.read_text(encoding="utf-8").strip()
    if len(token)!=64: raise ValueError("invalid worker token")
    conn=socket.create_connection(("127.0.0.1",a.port),timeout=5)
    conn.settimeout(3)
    def send(kind, **data):
        conn.sendall((json.dumps({"type":kind,**data})+"\n").encode())
    send("auth",token=token)
    conn.setblocking(True)
    from .codec.g7221 import Decoder
    decoder=Decoder()  # Initialize the bundled codec before detaching anything.
    import usb.core
    import usb.util
    import libusb_package
    from usb.backend import libusb1
    backend=libusb1.get_backend(find_library=libusb_package.find_library)
    matches=list(usb.core.find(find_all=True,idVendor=0x0416,idProduct=0x0602,backend=backend))
    if not matches: raise RuntimeError("未找到适配的 USB 0416:0602 接收器")
    dev=matches[0]; cfg=dev.get_active_configuration()
    voice=cfg[(3,0)]
    endpoints={ep.bEndpointAddress:ep for ep in voice}
    if not (0x84 in endpoints and endpoints[0x84].bmAttributes&3==3 and 0x05 in endpoints and endpoints[0x05].bmAttributes&3==2):
        raise RuntimeError("接收器端点布局不匹配")
    detached=[]; claimed=[]; readers=[]; phase=0; last_seq=None
    halt=False; active=False; start_at=0; keepalive=0; pending=b""; ignored_reports=0
    def stop_signal(*_):
        nonlocal halt
        halt=True
    signal.signal(signal.SIGTERM,stop_signal); signal.signal(signal.SIGINT,stop_signal)
    def command(prefix):
        n=dev.write(0x05,bytes(prefix)+b"\0"*(64-len(prefix)),timeout=1000)
        if n!=64: raise RuntimeError("USB 命令未完整发送")
    def stop_audio():
        nonlocal active,phase
        if phase>=1: command([1,1,0,0])
        if active: send("end")
        active=False; phase=0
    try:
        # macOS libusb capture detaches all HID services at once. Windows binds the
        # voice interface separately (WinUSB) and leaves keyboard interfaces on HID;
        # Raw Input in the GUI continues to handle their keys.
        interfaces=[i for i in cfg if i.bAlternateSetting==0 and (sys.platform!="win32" or i.bInterfaceNumber==3)]
        for interface in interfaces:
            number=interface.bInterfaceNumber
            if sys.platform=="darwin" and detached: continue
            try:
                if dev.is_kernel_driver_active(number):
                    dev.detach_kernel_driver(number); detached.append(number)
            except NotImplementedError:
                if sys.platform=="darwin":
                    dev.detach_kernel_driver(number); detached.append(number)
        for interface in interfaces:
            number=interface.bInterfaceNumber
            usb.util.claim_interface(dev,number); claimed.append(number)
            parser=None
            if number!=3:
                try:
                    descriptor=bytes(dev.ctrl_transfer(0x81,6,0x2200,number,4096,timeout=1000))
                    parser=HIDReports(descriptor)
                except usb.core.USBError as exc:
                    send("warning",message=f"接口 {number} 按键描述符读取失败：{exc}")
            for ep in interface:
                if ep.bEndpointAddress&0x80:
                    readers.append((ep,parser,number))
        command([1,8,1,0]); send("ready")
        while not halt:
            ready,_,_=select.select([conn],[],[],0)
            if ready:
                incoming=conn.recv(1024)
                if not incoming: break
                pending+=incoming
                if len(pending)>4096: raise ValueError("invalid parent message")
                while b"\n" in pending:
                    line,pending=pending.split(b"\n",1)
                    control=json.loads(line)
                    if control.get("type")=="start" and phase==0:
                        command([1,0x82,1,0]); command([1,8,1,0]); phase=1
                    elif control.get("type")=="stop": stop_audio()
                    elif control.get("type")=="exit": halt=True
            for ep,parser,number in readers:
                try: data=bytes(ep.read(ep.wMaxPacketSize,timeout=2))
                except usb.core.USBTimeoutError: continue
                if number==3:
                    # Recording follows the mapped key gesture in the GUI.
                    # A vendor voice request alone must not bypass the mapping.
                    if phase==1 and data[:4]==b"\x01\x08\x01\x00":
                        command([1,1,1,0]); phase=2
                    elif phase==2 and data[:4]==b"\x01\x01\x01\x00":
                        phase=3; active=True; start_at=time.monotonic(); keepalive=0; last_seq=None
                        decoder.reset(); send("start")
                    elif data.startswith(b"\x01\x81") and active:
                        if len(data)!=64: raise ValueError("truncated audio frame")
                        seq=tuple(int.from_bytes(data[n:n+4],"little") for n in (46,50))
                        if last_seq and any(b!=(v+1)&0xffffffff for v,b in zip(last_seq,seq)):
                            raise ValueError("USB 音频帧不连续")
                        last_seq=seq
                        send("pcm",data=base64.b64encode(decoder.decode(data[6:46])).decode())
                elif parser:
                    try:
                        events=parser.decode(data)
                    except ValueError:
                        ignored_reports+=1
                        if ignored_reports==1 or ignored_reports%100==0:
                            send("warning",message=f"已忽略异常按键报文（{ignored_reports}）")
                        continue
                    for trigger,down in events: send("key",trigger=trigger,down=down)
            if phase==3 and time.monotonic()>=keepalive:
                command([1,10,84,69]); keepalive=time.monotonic()+1
            if active and time.monotonic()-start_at>60: stop_audio()
    finally:
        try: stop_audio()
        except (OSError,RuntimeError): pass
        for number in reversed(claimed):
            try: usb.util.release_interface(dev,number)
            except usb.core.USBError: pass
        errors=[]
        for number in reversed(detached):
            try: dev.attach_kernel_driver(number)
            except usb.core.USBError as exc: errors.append(str(exc))
        usb.util.dispose_resources(dev)
        try: send("restored",errors=errors)
        except OSError: pass
        conn.close()
        if errors: raise RuntimeError("驱动恢复失败，请拔插接收器："+"; ".join(errors))


if __name__=="__main__":
    import sys
    run(sys.argv[1:])
