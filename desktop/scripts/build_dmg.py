#!/usr/bin/env python3
"""Package the App as a drag-to-Applications disk image.

The window uses a generated background (scripts/build_dmg_background.py) and
fixed icon positions, the way most Mac apps present themselves. The image is
not signed (no Developer ID), so the App still needs the usual first-launch
confirmation. Verified by mounting read-only and checking the signature.
"""
import argparse
import plistlib
import subprocess
import tempfile
from pathlib import Path

import dmgbuild

ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = ROOT / 'assets/dmg/background.png'
ICON = ROOT / 'build/macos/icons/AppIcon.icns'


def identity(app):
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    version = info['CFBundleShortVersionString']
    number = info['CFBundleVersion']
    archs = subprocess.run(['/usr/bin/lipo', '-archs', str(app / 'Contents/MacOS' / app.stem)],
                           capture_output=True, text=True, check=True).stdout.split()
    arch = archs[0] if len(archs) == 1 else 'universal'
    return f'{app.stem}-{version}-{number}-{arch}'


def settings(app):
    return {
        'files': [str(app)],
        'symlinks': {'Applications': '/Applications'},
        'icon_locations': {app.name: (154, 196), 'Applications': (466, 196)},
        'background': str(BACKGROUND),
        'window_rect': ((240, 240), (620, 400)),
        'icon_size': 128,
        'text_size': 13,
        'default_view': 'icon-view',
        'show_status_bar': False,
        'show_tab_view': False,
        'show_pathbar': False,
        'show_sidebar': False,
        'show_icon_preview': False,
        'badge_icon': '',
        'format': 'UDZO',
        'icon': str(ICON) if ICON.is_file() else None,
    }


def visible(path):
    return sorted(p.name for p in path.iterdir() if not p.name.startswith('.'))


def build(dist):
    dist = Path(dist).resolve()
    app = next(p for p in dist.iterdir() if p.suffix == '.app')
    output = dist / f'{identity(app)}.dmg'
    output.unlink(missing_ok=True)
    dmgbuild.build_dmg(str(output), app.stem, settings=settings(app))
    mounted = Path(tempfile.mkdtemp(prefix='rh-dmg-mnt-'))
    subprocess.run(['/usr/bin/hdiutil', 'attach', '-nobrowse', '-readonly',
                    str(output), '-mountpoint', str(mounted)], check=True, capture_output=True)
    try:
        subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict',
                        str(mounted / app.name)], check=True)
        assert (mounted / 'Applications').is_symlink(), '镜像里缺少「应用程序」快捷方式'
        assert visible(mounted) == sorted([app.name, 'Applications']), visible(mounted)
        assert ((mounted / '.background.tiff').is_file() or (mounted / '.background').is_dir()), '镜像里缺少背景图'
    finally:
        subprocess.run(['/usr/bin/hdiutil', 'detach', str(mounted)], check=True, capture_output=True)
        subprocess.run(['/bin/rmdir', str(mounted)], check=False)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist-dir', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.dist_dir))
