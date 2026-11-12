import json
import base64
from pathlib import Path
import types
import pytest
import usb.core
import usb.util
import usb.backend.libusb1
from remotehub import usb_worker
from remotehub.codec import g7221


@pytest.mark.parametrize("decoder_mode",["stub","fail","builtin"])
def test_usb_worker_handshake_and_restores_on_error(monkeypatch,tmp_path,decoder_mode):
    events=[]; commands=[]; cleanup=[]
    auth=tmp_path/"auth";auth.write_text("a"*64)
    fixture=json.loads((Path(__file__).parent/"fixtures/g7221-synthetic.json").read_text())
    payload=bytes.fromhex(fixture["payloads"][0])
    expected=g7221.Decoder().decode(payload)
    packets=[bytes.fromhex("018203")+bytes(61),bytes.fromhex("01080100")+bytes(60),bytes.fromhex("01010100")+bytes(60),bytes.fromhex("0181")+bytes(4)+payload+(1).to_bytes(4,"little")*2+bytes(10)]
    class Endpoint:
        def __init__(self,address,kind):self.bEndpointAddress=address;self.bmAttributes=kind;self.wMaxPacketSize=64
        def read(self,*args,**kwargs):
            if packets:return packets.pop(0)
            raise usb.core.USBTimeoutError("empty")
    class Interface(list):bInterfaceNumber=3;bAlternateSetting=0
    interface=Interface([Endpoint(0x84,3),Endpoint(0x05,2)])
    class Config(list):
        def __getitem__(self,key):return interface if key==(3,0) else super().__getitem__(key)
    class Device:
        iSerialNumber=0
        def get_active_configuration(self):return Config([interface])
        def is_kernel_driver_active(self,n):return True
        def detach_kernel_driver(self,n):cleanup.append(("detach",n))
        def attach_kernel_driver(self,n):cleanup.append(("restore",n))
        def write(self,ep,data,timeout):commands.append(data[:4]);assert len(data)==64;return len(data)
    dev=Device()
    class Connection:
        def settimeout(self,*_):pass
        def setblocking(self,*_):pass
        def sendall(self,data):events.append(json.loads(data))
        def recv(self,_):
            return b'{"type":"exit"}\n' if any(e["type"]=="pcm" for e in events) else b'{"type":"start"}\n'
        def close(self):cleanup.append(("socket-close",))
    conn=Connection()
    class Decoder:
        def __init__(self,*_):pass
        def reset(self):events.append({"type":"decoder-reset"})
        def decode(self,payload):
            assert len(payload)==40
            if decoder_mode=="fail":raise RuntimeError("decoder failed")
            return b"\0"*640
    class RealDecoder(g7221.Decoder):
        def reset(self):
            super().reset();events.append({"type":"decoder-reset"})
    monkeypatch.setattr(g7221,"Decoder",RealDecoder if decoder_mode=="builtin" else Decoder)
    monkeypatch.setattr(usb_worker.socket,"create_connection",lambda *a,**k:conn)
    monkeypatch.setattr(usb_worker.select,"select",lambda *a:([conn],[],[]) if len(commands)==1 or any(e["type"]=="pcm" for e in events) else ([],[],[]))
    monkeypatch.setattr(usb_worker.signal,"signal",lambda *a:None)
    def find(**kwargs):
        assert kwargs["idVendor"]==0x0416 and kwargs["idProduct"]==0x0602
        return [dev]
    monkeypatch.setattr(usb.core,"find",find)
    monkeypatch.setattr(usb.backend.libusb1,"get_backend",lambda **k:None)
    def no_serial_lookup(*args):raise AssertionError("Model matching must not require USB serial access")
    monkeypatch.setattr(usb.util,"get_string",no_serial_lookup)
    monkeypatch.setattr(usb.util,"claim_interface",lambda d,n:cleanup.append(("claim",n)))
    monkeypatch.setattr(usb.util,"release_interface",lambda d,n:cleanup.append(("release",n)))
    monkeypatch.setattr(usb.util,"dispose_resources",lambda d:cleanup.append(("dispose",)))
    args=["--port","8769","--auth-file",str(auth)]
    if decoder_mode=="fail":
        with pytest.raises(RuntimeError,match="decoder failed"):usb_worker.run(args)
    else:usb_worker.run(args)
    assert commands[:4]==[bytes.fromhex(h) for h in ("01080100","01820100","01080100","01010100")]
    assert commands[-1]==bytes.fromhex("01010000")
    assert cleanup.index(("release",3))<cleanup.index(("restore",3))
    assert events[-1]=={"type":"restored","errors":[]}
    assert events.index({"type":"decoder-reset"}) < events.index({"type":"start"})
    if decoder_mode=="builtin":
        actual=next(e["data"] for e in events if e["type"]=="pcm")
        assert base64.b64decode(actual)==expected
