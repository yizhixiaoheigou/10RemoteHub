#!/usr/bin/env python3
"""Collect exact-version notices; stop instead of silently shipping missing ones.

--supplement supplies notices absent from wheels and the native-library inventory.
See RELEASE.md for the schema. This inventories notices, not a legal verdict.
"""
import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/licenses'
BUNDLED = {'pyside6', 'pyside6-essentials', 'pyside6-addons', 'shiboken6', 'pynput',
           'numpy', 'hidapi', 'pyusb', 'libusb-package', 'platformdirs', 'six', 'pyinstaller'}
MAC = {'pyobjc-core', 'pyobjc-framework-quartz', 'pyobjc-framework-cocoa',
       'pyobjc-framework-applicationservices', 'pyobjc-framework-coretext'}


def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def notice_files(dist):
    """PEP 639 paths and legacy dist-info notices, without private dist._path."""
    for file in dist.files or ():
        if Path(str(file)).suffix.lower() in {'.py', '.pyc', '.so', '.dylib', '.dll', '.pyd', '.a', '.o', '.exe', '.lib'}:
            continue
        parts = Path(str(file)).parts
        if any(p.lower() in ('licenses', 'license') for p in parts) or re.match(
                r'^(license|licence|copying|notice|authors)([._-]|$)', Path(str(file)).name, re.I):
            source = Path(dist.locate_file(file))
            if source.is_file():
                yield source


def runtime_distributions(analysis, installed, required):
    """Find wheel owners of files actually selected by PyInstaller.

    Some Qt wheels share __init__.py; an already-covered shared file does not
    mean that the PDF or WebEngine runtime was bundled.
    """
    def strings(value):
        if isinstance(value, (tuple, list)):
            for item in value:
                yield from strings(item)
        elif isinstance(value, str):
            yield value
    selected = {str(Path(value).resolve()) for value in strings(
        ast.literal_eval(Path(analysis).read_text(encoding='utf-8')))
        if 'site-packages' in value and Path(value).is_file()}
    owners = {name: {str(Path(dist.locate_file(file)).resolve()) for file in dist.files or ()} & selected
              for name, dist in installed.items()}
    covered = set().union(*(owners.get(name, set()) for name in required))
    added = set()
    for name, files in sorted(owners.items()):
        if files - covered:
            added.add(name)
            covered.update(files)
    return added


def collect(out=OUT, supplement=None, distributions=None, platform=None, analysis=None):
    out = Path(out)
    # Keep previous evidence. Each build gets a new staging directory from the CLI.
    out.mkdir(parents=True, exist_ok=False)
    for source in sorted((ROOT / 'licenses').iterdir()):
        if source.is_file():
            shutil.copy2(source, out / source.name)
    shutil.copy2(ROOT.parent / 'LICENSE', out / 'PROJECT-LICENSE.txt')
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.txt', out / 'THIRD_PARTY_NOTICES.txt')
    shutil.copy2(ROOT / 'native/macos-audio/LICENSE.txt', out / 'Apple-audio-LICENSE.txt')
    shutil.copy2(ROOT / 'native/libusb-LICENSE.txt', out / 'libusb-LICENSE.txt')
    extra = {}
    if supplement:
        supplement = Path(supplement).resolve()
        data = json.loads(supplement.read_text(encoding='utf-8'))
        extra = {normalize(row['name']):row for row in data['components']}
    required = BUNDLED | (MAC if (platform or sys.platform) == 'darwin' else set())
    installed = {normalize(d.metadata['Name']):d for d in
                 (metadata.distributions() if distributions is None else distributions)}
    if analysis:
        required |= runtime_distributions(analysis, installed, required)
    errors, components = [], []
    vendor_root = ROOT / 'licenses/vendor'
    vendor_index = vendor_root / 'SOURCES.json'
    vendor = json.loads(vendor_index.read_text())['upstream_archives'] if vendor_index.is_file() else []

    def add(name, version, files, supplied):
        row = {'name':name, 'version':version, 'licenses':[]}
        target = out / name
        target.mkdir(exist_ok=True)
        notice_root = ((supplement.parent / supplied['license_root']).resolve()
                       if supplied.get('license_root') else None)
        for i, source in enumerate(files):
            if not source.is_file():
                errors.append('Missing notice: ' + str(source)); continue
            if notice_root and source.resolve().is_relative_to(notice_root):
                # Attribution JSON refers to neighbouring license files. Preserve
                # that tree instead of flattening and renaming every notice.
                dest = target / 'upstream' / source.resolve().relative_to(notice_root)
            else:
                dest = target / f'{i:03d}-{source.name}'
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            row['licenses'].append({'path':dest.relative_to(out).as_posix(),
                                   'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
        if not row['licenses']:
            errors.append(f'Missing notices for {name}=={version}')
        if supplied:
            for key in ('source_url', 'source_sha256', 'build_notes', 'runtime_provenance'):
                if supplied.get(key): row[key] = supplied[key]
        components.append(row)

    for name in sorted(required):
        dist = installed.get(name)
        if dist is None:
            errors.append('Required distribution not installed: ' + name); continue
        supplied = extra.get(name, {})
        if supplied and supplied.get('version') != dist.version:
            errors.append('Supplement version mismatch: ' + name); supplied = {}
        files = list(notice_files(dist))
        files += [supplement.parent / p for p in supplied.get('license_files', [])]
        family = 'pyside6' if name in {'pyside6', 'pyside6-essentials', 'pyside6-addons', 'shiboken6'} else name
        for source in vendor:
            if source['name'] == family and source['version'] == dist.version:
                for notice in source['notices']:
                    file = vendor_root / notice['path']
                    if hashlib.sha256(file.read_bytes()).hexdigest() != notice['sha256']:
                        raise RuntimeError('Changed upstream notice: ' + str(file))
                    files.append(file)
                supplied = {'source_url':source['source_url'], 'source_sha256':source['source_sha256'], **supplied}
        add(name, dist.version, files, supplied)
    native = ['qt', 'ffmpeg', 'python', 'libusb']
    if (platform or sys.platform) == 'darwin':
        native.append('libusb-helper')
    for name in native:
        supplied = extra.get(name, {})
        if not supplied.get('version'):
            errors.append('Missing native inventory: ' + name); continue
        add(name, supplied['version'],
            [supplement.parent / p for p in supplied.get('license_files', [])], supplied)
    manifest = {'schema':1, 'platform':platform or sys.platform, 'components':components}
    (out / 'components.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    from release_policy import verify_licenses
    paths = {p.relative_to(out).as_posix():p for p in out.rglob('*') if p.is_file()}
    errors += verify_licenses(lambda n:paths[n].read_bytes(), set(paths), '')
    if errors:
        raise RuntimeError('\n'.join(sorted(set(errors))))
    return out


if __name__ == '__main__':
    import tempfile
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--supplement', type=Path)
    p.add_argument('--analysis', type=Path, help='PyInstaller Analysis-00.toc for runtime dependency closure')
    args = p.parse_args()
    ROOT.joinpath('build').mkdir(exist_ok=True)
    # No deletion of previous build material; build.py consumes the returned path.
    base = Path(tempfile.mkdtemp(prefix='license-stage-', dir=ROOT / 'build'))
    print(collect(base / 'licenses', args.supplement, analysis=args.analysis))
