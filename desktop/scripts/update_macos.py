#!/usr/bin/env python3
"""Replace a verified App bundle without merging obsolete files or installing services."""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

LSREGISTER = ('/System/Library/Frameworks/CoreServices.framework/Frameworks/'
              'LaunchServices.framework/Support/lsregister')


def verify(path):
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(path)], check=True)


def copy_bundle(source, destination):
    subprocess.run(['/usr/bin/ditto', str(source), str(destination)], check=True)


def unregister(path):
    """LaunchServices indexes every .app it sees; drop stale copies from the list."""
    try:
        subprocess.run([LSREGISTER, '-u', str(path)], capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


def clear_stale_workdirs(parent, keep=None):
    """Remove update copies left by earlier runs; each one shows up as an extra App."""
    for entry in Path(parent).glob('.10RemoteHub-update-*'):
        if not entry.is_dir() or (keep and entry.resolve() == Path(keep).resolve()):
            continue
        for app in entry.rglob('*.app'):
            unregister(app)
        shutil.rmtree(entry, ignore_errors=True)


def hide_leftover_apps(work):
    """Keep a failed update for diagnosis without registering it as an App."""
    for app in Path(work).rglob('*.app'):
        unregister(app)
        app.rename(app.with_name(app.name + '.rollback'))


def is_running(destination):
    executable = destination / 'Contents/MacOS/10RemoteHub'
    result = subprocess.run(['/usr/bin/pgrep', '-f', '^' + re.escape(str(executable)) + r'($| )'],
                            stdout=subprocess.DEVNULL, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError('无法确认应用是否已退出，尚未替换')
    return result.returncode == 0


def replace_app(source, destination, *, validate=verify, copy=copy_bundle, running=is_running):
    source, destination = Path(source), Path(destination)
    if destination.is_symlink() or not source.is_dir():
        raise RuntimeError('应用路径不符合预期，尚未替换')
    if source.resolve() == destination.resolve():
        raise RuntimeError('来源和安装位置不能相同')
    if running(destination):
        raise RuntimeError('请先从 10RemoteHub 状态栏菜单退出应用，再运行更新')
    validate(source)
    # Same-volume renames preserve a complete rollback copy, unlike ditto-overwrite.
    work = Path(tempfile.mkdtemp(prefix='.10RemoteHub-update-', dir=destination.parent))
    clear_stale_workdirs(destination.parent, keep=work)
    candidate = work / 'new.app'
    backup = work / 'previous.app'
    try:
        copy(source, candidate)
        validate(candidate)
        if running(destination):
            raise RuntimeError('应用在构建期间重新打开了；请退出后重试，尚未替换')
        existed = destination.exists()
        if existed:
            destination.rename(backup)
        try:
            candidate.rename(destination)
            validate(destination)
        except Exception:
            if destination.exists():
                destination.rename(work / 'failed.app')
            if existed:
                backup.rename(destination)
            raise
    except Exception as exc:
        # Leave no .app behind: a leftover copy would register as another App.
        hide_leftover_apps(work)
        raise RuntimeError(f'{exc}\n更新暂存目录：{work}') from exc
    if existed:
        unregister(backup)
        rolled_back = backup.with_name('previous.app.rollback')
        backup.rename(rolled_back)
        backup = rolled_back
    return backup if existed else None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    # Full release verification is mandatory before touching /Applications.
    from verify_device_delivery import verify as verify_delivery
    verify_delivery(args.source)
    backup = replace_app(args.source.resolve(), Path('/Applications/10RemoteHub.app'))
    print('主程序已更新；没有安装采集服务或虚拟麦克风，也没有更改系统授权。')
    if backup:
        print('旧版备份：', backup)
