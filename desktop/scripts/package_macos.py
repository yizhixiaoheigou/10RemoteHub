#!/usr/bin/env python3
"""Make a single reviewable installer: app plus optional microphone component.

Only creates packages. Does not run installer or restart CoreAudio.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import xml.sax.saxutils as xml

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument("--dist-dir",type=Path,default=Path("dist/macos"),help="App and installer directory, relative to desktop/ unless absolute")
a=p.parse_args()
dist=(root/a.dist_dir).resolve()
brand=json.loads((root/"remotehub/branding.json").read_text());name=brand["product_name"]
app=dist/(name+".app")
info=plistlib.loads((app/"Contents/Info.plist").read_bytes())
version=info.get("CFBundleShortVersionString","0.0.0");build=info.get("CFBundleVersion","0")
audio=app/"Contents/Resources/components/RemoteHubAudioComponent.pkg"
collector=app/"Contents/Resources/components/RemoteHubDevice.pkg"
if not app.is_dir() or not audio.is_file():raise SystemExit("Build desktop app and microphone component first")
packages=root/"build/macos/installer";packages.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,COPYFILE_DISABLE="1")
def run(*args):subprocess.run([str(x) for x in args],check=True,env=env)
run("pkgbuild","--component",app,"--install-location","/Applications","--identifier","org.remotehub.desktop","--version",version,packages/"Desktop.pkg")
import shutil
shutil.copyfile(audio,packages/"Audio.pkg")
collector_outline = collector_choice = collector_reference = ""
if collector.is_file():
    shutil.copyfile(collector, packages/"Collector.pkg")
    collector_outline = '<line choice="collector"/>'
    collector_choice = '<choice id="collector" title="设备采集程序（按键与声音）" description="由主程序管理；连接时接管这款接收器，退出后释放。" start_selected="true"><pkg-ref id="org.remotehub.device-helper"/></choice>'
    collector_reference = '<pkg-ref id="org.remotehub.device-helper" version="1.0.0">Collector.pkg</pkg-ref>'
distribution=f'''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>{xml.escape(name)} {version} · 安装</title>
  <options customize="always" require-scripts="true"/>
  <domains enable_localSystem="true" enable_currentUserHome="false"/>
  <choices-outline><line choice="desktop"/>{collector_outline}<line choice="audio"/></choices-outline>
  <choice id="desktop" title="{xml.escape(name)} 桌面程序" start_selected="true"><pkg-ref id="org.remotehub.desktop"/></choice>
  {collector_choice}
  <choice id="audio" title="虚拟麦克风" description="仅使用遥控器麦克风时需要。安装结束会自动启用，声音和录音将短暂中断，请先暂停通话与录音。" start_selected="false"><pkg-ref id="org.remotehub.audio"/></choice>
  <pkg-ref id="org.remotehub.desktop" version="{version}">Desktop.pkg</pkg-ref>
  {collector_reference}
  <pkg-ref id="org.remotehub.audio" version="0.1.1">Audio.pkg</pkg-ref>
</installer-gui-script>'''
path=packages/"Distribution.xml";path.write_text(distribution)
run("productbuild","--distribution",path,"--package-path",packages,dist/(name+"-Setup.pkg"))
print("Installer created; no system components installed.")
