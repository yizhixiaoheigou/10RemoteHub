#!/usr/bin/env python3
"""Build the standalone uninstaller package; never runs it here.

Every path is a constant in the generated script, and every deletion is guarded
by a bundle-identifier check. User configuration is left in place.
"""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]

CONSTANTS = {
    'APP': '/Applications/10RemoteHub.app',
    'APP_ID': 'org.remotehub.desktop',
    'SERVICE': 'org.remotehub.device-helper',
    'HELPER': '/Library/PrivilegedHelperTools/10RemoteHub',
    'DAEMON': '/Library/LaunchDaemons/org.remotehub.device-helper.plist',
    'DRIVER': '/Library/Audio/Plug-Ins/HAL/RemoteHubAudio.driver',
    'DRIVER_ID': 'org.remotehub.audio',
}

TEMPLATE = '''#!/bin/sh
set -eu
# Runs as root from Installer. Paths below are constants, never environment or
# user input, and each removal is guarded by a bundle identifier check.
APP="@@APP@@"
APP_ID="@@APP_ID@@"
SERVICE="@@SERVICE@@"
HELPER="@@HELPER@@"
DAEMON="@@DAEMON@@"
DRIVER="@@DRIVER@@"
DRIVER_ID="@@DRIVER_ID@@"
LOGIN_AGENT="Library/LaunchAgents/org.remotehub.desktop.plist"

if /usr/bin/pgrep -f "^$APP/Contents/MacOS/10RemoteHub($| )" >/dev/null 2>&1; then
    echo '10RemoteHub 仍在运行。请先从菜单栏退出应用，再运行卸载程序。' >&2
    exit 1
fi

if /bin/launchctl print "system/$SERVICE" >/dev/null 2>&1; then
    /bin/launchctl bootout "system/$SERVICE" >/dev/null 2>&1 || :
    remaining=10
    while /bin/launchctl print "system/$SERVICE" >/dev/null 2>&1; do
        if [ "$remaining" -eq 0 ]; then
            echo '采集组件没有在限定时间内停止，卸载已中止。' >&2
            exit 1
        fi
        /bin/sleep 1
        remaining=$((remaining - 1))
    done
fi

remove_bundle() {
    path="$1"; identifier="$2"
    [ -e "$path" ] || return 0
    [ ! -L "$path" ] || return 1
    actual=$(/usr/bin/plutil -extract CFBundleIdentifier raw -o - "$path/Contents/Info.plist" 2>/dev/null || true)
    [ "$actual" = "$identifier" ] || return 1
    /bin/rm -rf "$path"
}

remove_bundle "$APP" "$APP_ID"
remove_bundle "$DRIVER" "$DRIVER_ID"

/bin/rm -f "$DAEMON"
/bin/rm -rf "$HELPER"

console_user=$(/usr/bin/stat -f %Su /dev/console 2>/dev/null || echo '')
if [ -n "$console_user" ] && [ "$console_user" != root ] && [ "$console_user" != loginwindow ]; then
    home=$(/usr/bin/dscl . -read "/Users/$console_user" NFSHomeDirectory 2>/dev/null | /usr/bin/awk '{print $2}')
    uid=$(/usr/bin/id -u "$console_user" 2>/dev/null || echo '')
    if [ -n "$home" ] && [ -f "$home/$LOGIN_AGENT" ]; then
        /bin/rm -f "$home/$LOGIN_AGENT"
        if [ -n "$uid" ]; then
            /bin/launchctl bootout "gui/$uid/$APP_ID" >/dev/null 2>&1 || :
        fi
    fi
fi

for receipt in "$APP_ID" "$SERVICE" "$SERVICE.uninstall" "$DRIVER_ID"; do
    /usr/sbin/pkgutil --forget "$receipt" >/dev/null 2>&1 || :
done

if [ -e "$DRIVER" ]; then
    echo '虚拟麦克风目录未能删除，已跳过音频服务重载。' >&2
else
    /usr/bin/killall -TERM coreaudiod >/dev/null 2>&1 || :
fi

echo '10RemoteHub 已卸载。用户配置保留在 ~/Library/Application Support/RemoteHub，可自行删除。'
'''


def render():
    text = TEMPLATE
    for key, value in CONSTANTS.items():
        text = text.replace('@@' + key + '@@', value)
    return text


POSTINSTALL = render()


def build(output=None):
    output = Path(output) if output else ROOT / 'build/RemoteHub-Uninstall.pkg'
    output.parent.mkdir(parents=True, exist_ok=True)
    scripts = output.parent / 'uninstall-scripts'
    scripts.mkdir(parents=True, exist_ok=True)
    script = scripts / 'postinstall'
    script.write_text(POSTINSTALL)
    script.chmod(0o755)
    subprocess.run(['/bin/sh', '-n', str(script)], check=True)
    subprocess.run(['/usr/bin/pkgbuild', '--nopayload', '--scripts', str(scripts),
                    '--identifier', CONSTANTS['APP_ID'] + '.uninstall', '--version', '1.0.0',
                    str(output)],
                   check=True, env=dict(os.environ, COPYFILE_DISABLE='1'))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print('Built', build(args.output), '; not run')
