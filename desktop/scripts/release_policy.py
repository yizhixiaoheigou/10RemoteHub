"""Platform-independent release artifact checks; no installation or system calls."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

# Reviewed Qt modules used by Widgets/Multimedia and their transitive runtime.
QT_MODULES = frozenset('Core Gui Widgets Network Multimedia MultimediaWidgets Svg SvgWidgets '
    'OpenGL OpenGLWidgets Concurrent DBus Qml QmlMeta QmlModels QmlWorkerScript Quick'.split())
FORBIDDEN = ('virtualkeyboard', 'qtcharts', 'qtdatavisualization', 'qtgraphs', 'qtquick3d',
             'qtwebengine', 'qtpdf', 'libqpdf', 'qpdf.dll', 'libicocodec', 'libg7221', 'unicorn')
REQUIRED_LICENSES = ('PROJECT-LICENSE.txt', 'THIRD_PARTY_NOTICES.txt', 'LGPL-3.0.txt',
                     'LGPL-2.1.txt', 'GPL-3.0.txt', 'SOURCE.md', 'components.json')


def validate_names(names):
    errors = []
    for name in names:
        if name.startswith('__MACOSX/'):
            continue
        lower = name.lower()
        if any(part in lower for part in FORBIDDEN):
            errors.append('Unapproved bundled component: ' + name)
        match = re.search(r'/(?:lib)?Qt(?:6)?([A-Z][A-Za-z0-9]*)(?:\.framework/|\.dll$|\.so(?:\.|$))', name)
        if match and match[1] not in QT_MODULES:
            errors.append('Unreviewed Qt module: ' + match[1])
    return errors


def verify_licenses(read, names, prefix):
    errors = []
    for name in REQUIRED_LICENSES:
        if prefix + name not in names:
            errors.append('Missing license file: ' + name)
    if prefix + 'components.json' not in names:
        return errors
    try:
        manifest = json.loads(read(prefix + 'components.json'))
        if not manifest.get('components'):
            raise ValueError('empty component manifest')
        for component in manifest['components']:
            if not component.get('version'):
                errors.append('Missing exact version: ' + component['name'])
            if not component.get('licenses'):
                errors.append('Missing notices: ' + component['name'])
            for item in component.get('licenses', []):
                if Path(item['path']).is_absolute() or '..' in Path(item['path']).parts:
                    errors.append('Unsafe notice path'); continue
                file = prefix + item['path']
                if file not in names or hashlib.sha256(read(file)).hexdigest() != item['sha256']:
                    errors.append('Missing/changed notice: ' + item['path'])
        # These native libraries are not captured by pip metadata alone.
        covered = {row['name'] for row in manifest['components']}
        for name in ('qt', 'ffmpeg', 'python', 'libusb'):
            if name not in covered:
                errors.append('Missing native component inventory: ' + name)
        if manifest.get('platform') == 'darwin' and 'libusb-helper' not in covered:
            errors.append('Missing native component inventory: libusb-helper')
        for row in manifest['components']:
            if row['name'] in ('qt', 'ffmpeg', 'libusb', 'libusb-helper', 'pynput', 'pyside6', 'shiboken6'):
                if (not str(row.get('source_url', '')).startswith('https://')
                        or not re.fullmatch('[a-f0-9]{64}', row.get('source_sha256', ''))
                        or not row.get('build_notes')):
                    errors.append('Missing corresponding source/build evidence: ' + row['name'])
    except (ValueError, KeyError, TypeError) as exc:
        errors.append('Invalid license manifest: ' + str(exc))
    return errors


def verify(path):
    path = Path(path)
    if path.is_file():
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            errors = validate_names(names)
            candidates = {name.rsplit('/', 1)[0] + '/' for name in names
                          if name.endswith('/licenses/THIRD_PARTY_NOTICES.txt') and not name.startswith('__MACOSX/')}
            if len(candidates) != 1:
                errors.append('Expected one license directory')
            else:
                errors += verify_licenses(archive.read, names, candidates.pop())
    else:
        paths = {p.relative_to(path).as_posix():p for p in path.rglob('*') if p.is_file()}
        names = set(paths)
        errors = validate_names(names)
        prefix = 'Contents/Resources/licenses/' if path.suffix == '.app' else '_internal/licenses/'
        errors += verify_licenses(lambda n:paths[n].read_bytes(), names, prefix)
    if errors:
        raise RuntimeError('\n'.join(sorted(set(errors))))
    return {'license_inventory':True, 'native_component_policy':True}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('artifact', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.artifact)))
