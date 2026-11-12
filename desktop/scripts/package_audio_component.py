"""Build an audio payload plus a standalone installer with visible setup notice.

Only build packages; never install or restart the audio service here.
"""
import html
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]


def build():
    driver = ROOT / 'build/RemoteHubAudio.driver'
    info = plistlib.loads((driver / 'Contents/Info.plist').read_bytes())
    version = info['CFBundleShortVersionString']
    brand = json.loads((ROOT / 'remotehub/branding.json').read_text())
    build_dir = ROOT / 'build/audio-installer'
    scripts = build_dir / 'scripts'
    resources = build_dir / 'resources'
    scripts.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'native/macos-audio/installer/postinstall', scripts / 'postinstall')
    shutil.copyfile(ROOT / 'build/audio-plugin-probe', scripts / 'audio-plugin-probe')
    for path in scripts.iterdir():
        path.chmod(0o755)
    env = dict(os.environ, COPYFILE_DISABLE='1')
    payload = ROOT / 'build/RemoteHubAudioComponent.pkg'
    subprocess.run(['pkgbuild', '--root', str(driver), '--scripts', str(scripts),
                    '--filter', '/\\._', '--install-location', '/Library/Audio/Plug-Ins/HAL/RemoteHubAudio.driver',
                    '--identifier', 'org.remotehub.audio', '--version', version, str(payload)],
                   check=True, env=env)
    name = html.escape(brand['microphone_name'])
    (resources / 'Welcome.html').write_text(
        '<html><meta charset="utf-8"><body style="font-family:-apple-system;font-size:14px">'
        f'<h2>安装 {name}</h2><p>仅使用遥控器麦克风时需要安装。</p>'
        '<p><b>安装结束时，声音和录音会短暂中断。请先暂停通话和录音。</b></p>'
        '<p>安装器会自动启用并检查麦克风，无需另外运行命令。</p></body></html>')
    (resources / 'Conclusion.html').write_text(
        '<html><meta charset="utf-8"><body style="font-family:-apple-system;font-size:14px">'
        f'<p>请在识别软件的麦克风选项中选择 <b>{name}</b>，然后按遥控器语音键说话。</p>'
        '</body></html>')
    distribution = build_dir / 'Distribution.xml'
    distribution.write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>{escape(brand['product_name'])} 虚拟麦克风</title>
  <welcome file="Welcome.html"/>
  <conclusion file="Conclusion.html"/>
  <options customize="never" require-scripts="true" hostArchitectures="arm64,x86_64"/>
  <domains enable_localSystem="true" enable_currentUserHome="false"/>
  <choices-outline><line choice="audio"/></choices-outline>
  <choice id="audio" title="虚拟麦克风"><pkg-ref id="org.remotehub.audio"/></choice>
  <pkg-ref id="org.remotehub.audio" version="{escape(version)}">RemoteHubAudioComponent.pkg</pkg-ref>
</installer-gui-script>''')
    subprocess.run(['productbuild', '--distribution', str(distribution), '--resources', str(resources),
                    '--package-path', str(payload.parent), str(ROOT / 'build/RemoteHubAudio.pkg')],
                   check=True, env=env)


if __name__ == '__main__':
    build()
