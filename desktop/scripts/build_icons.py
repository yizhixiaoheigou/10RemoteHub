"""Render the editable SVG master and package ICNS / multi-size ICO icons."""
from pathlib import Path
import struct
import subprocess
import sys
from PySide6.QtCore import Qt,QBuffer,QByteArray,QIODevice
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer

root=Path(__file__).resolve().parents[1]
if sys.platform not in ("darwin","win32"):raise SystemExit("Icons are built for macOS and Windows only")
target={"darwin":"macos","win32":"windows"}[sys.platform]
out=root/"build"/target/"icons"; out.mkdir(parents=True,exist_ok=True)
renderer=QSvgRenderer(str(root/"remotehub/assets/app-icon.svg"))
if not renderer.isValid():raise RuntimeError("Invalid application icon SVG")
source=QImage(1024,1024,QImage.Format.Format_ARGB32_Premultiplied)
source.fill(Qt.GlobalColor.transparent)
painter=QPainter(source)
renderer.render(painter)
painter.end()
if not source.save(str(root/"remotehub/assets/app-icon.png")):raise RuntimeError("Cannot render application icon")
if source.isNull() or not source.hasAlphaChannel():raise RuntimeError("Missing transparent application icon")
def scaled(size):return source.scaled(size,size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
if sys.platform=="darwin":
    iconset=out/"AppIcon.iconset"; iconset.mkdir(exist_ok=True)
    for size in (16,32,128,256,512):
        for factor in (1,2):
            name=f"icon_{size}x{size}"+("@2x" if factor==2 else "")+".png"
            if not scaled(size*factor).save(str(iconset/name)):raise RuntimeError("Cannot encode icon size")
    subprocess.run(["iconutil","-c","icns",str(iconset),"-o",str(out/"AppIcon.icns")],check=True)
# PNG-backed ICO entries support current Windows releases, preserve alpha,
# and avoid depending on a separate image conversion package.
entries=[]
for size in (16,24,32,48,64,128,256):
    data=QByteArray(); buffer=QBuffer(data); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not scaled(size).save(buffer,"PNG"):raise RuntimeError("Cannot encode icon size")
    entries.append((size,bytes(data)))
offset=6+16*len(entries); header=struct.pack("<HHH",0,1,len(entries)); body=b""
for size,data in entries:
    header+=struct.pack("<BBBBHHII",size%256,size%256,0,0,1,32,len(data),offset)
    offset+=len(data); body+=data
(out/"AppIcon.ico").write_bytes(header+body)
print("Icon containers written to",out)
