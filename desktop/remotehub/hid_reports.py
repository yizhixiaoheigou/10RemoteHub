"""Small bounded HID input descriptor parser for captured USB interfaces."""
from dataclasses import dataclass


@dataclass
class Field:
    offset: int
    size: int
    count: int
    page: int
    usages: list[int]
    minimum: int
    variable: bool


class HIDReports:
    def __init__(self, descriptor: bytes):
        self.fields={}; self.offsets={}; self.previous=set()
        self.has_ids=False
        page=size=count=report=minimum=0
        usages=[]; low=high=None; stack=[]
        i=0
        while i<len(descriptor):
            prefix=descriptor[i]; i+=1
            if prefix==0xfe:
                if i+2>len(descriptor): raise ValueError("HID long item truncated")
                length=descriptor[i]
                if i+2+length>len(descriptor):raise ValueError("HID long item truncated")
                i+=2+length; continue
            length=[0,1,2,4][prefix&3]
            if i+length>len(descriptor): raise ValueError("HID item truncated")
            data=descriptor[i:i+length]; i+=length
            value=int.from_bytes(data,"little")
            signed=int.from_bytes(data,"little",signed=True) if data else 0
            kind=(prefix>>2)&3; tag=prefix>>4
            if kind==1:
                if tag==0: page=value
                elif tag==1: minimum=signed
                elif tag==7: size=value
                elif tag==8: report=value; self.has_ids=True
                elif tag==9: count=value
                elif tag==10: stack.append((page,size,count,report,minimum))
                elif tag==11:
                    if not stack: raise ValueError("HID global stack underflow")
                    page,size,count,report,minimum=stack.pop()
            elif kind==2:
                if tag==0: usages.append(value)
                elif tag==1: low=value
                elif tag==2: high=value
            elif kind==0:
                if tag==8:
                    if size>32 or count>1024 or size*count>8192: raise ValueError("HID field too large")
                    if not usages and low is not None and high is not None and 0<=high-low<1024:
                        usages=list(range(low,high+1))
                    offset=self.offsets.get(report,0)
                    if not value&1 and page in (7,9,12):
                        self.fields.setdefault(report,[]).append(Field(offset,size,count,page,usages,minimum,bool(value&2)))
                    self.offsets[report]=offset+size*count
                usages=[]; low=high=None

    def decode(self, packet: bytes):
        if not packet: return []
        report=packet[0] if self.has_ids else 0
        data=packet[1:] if self.has_ids else packet
        # Vendor status/mouse-only reports do not contain keys we consume.
        if not self.fields.get(report):
            return []
        if len(data)*8<self.offsets.get(report,0):
            raise ValueError("HID input report truncated")
        bits=int.from_bytes(data,"little")
        current=set()
        for f in self.fields.get(report,[]):
            for i in range(f.count):
                raw=(bits>>(f.offset+i*f.size))&((1<<f.size)-1)
                if f.page == 7 and not f.variable and 0 < raw < 4:
                    return []  # keyboard rollover/error; retain the previous state
                if not raw: continue
                index=i if f.variable else raw-f.minimum
                if not 0<=index<len(f.usages):
                    continue
                usage=f.usages[index]
                if f.page==7 and usage<4: continue
                current.add((report,f"hid:{f.page}:{usage}"))
        previous={p for p in self.previous if p[0]==report}
        events=[(s,False) for _,s in sorted(previous-current)]+[(s,True) for _,s in sorted(current-previous)]
        self.previous=(self.previous-previous)|current
        return events
