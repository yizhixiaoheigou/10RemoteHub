"""Collect pinned python-build-standalone notices and build recipes for macOS.

The full distribution provides metadata/notices; install-only binaries establish
runtime provenance. The recipe archive includes upstream download hashes and
patches. This does not rebuild CPython or claim bit-for-bit reproducibility.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def prepare(base):
    base = Path(base)
    pins = json.loads((ROOT / 'licenses/python-standalone.json').read_text())
    build = Path(sys.base_prefix) / 'BUILD'
    if (sys.platform != 'darwin' or not build.is_file()
            or build.read_text().strip() != pins['build']
            or '.'.join(map(str, sys.version_info[:3])) != pins['python_version']):
        raise RuntimeError('Python runtime differs from the reviewed standalone build')
    cache = base / 'python-standalone'
    cache.mkdir(parents=True, exist_ok=True)
    for item in pins['archives']:
        path = cache / item['filename']
        if not path.exists():
            partial = path.with_suffix(path.suffix + '.part')
            with urllib.request.urlopen(item['url'], timeout=60) as response, partial.open('wb') as out:
                total = 0
                while chunk := response.read(1 << 20):
                    total += len(chunk)
                    if total > item['size']:
                        raise RuntimeError('Python provenance archive exceeds pinned size')
                    out.write(chunk)
            if hashlib.sha256(partial.read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('Python provenance archive checksum mismatch')
            partial.replace(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('Changed Python provenance archive: ' + path.name)
    notices = cache / 'notices'
    notices.mkdir(exist_ok=True)
    full = next(x for x in pins['archives'] if x['role'] == 'distribution-metadata')
    # macOS bsdtar handles zstd; it is used to read named files, never extractall.
    archive = cache / full['filename']
    metadata = json.loads(subprocess.check_output(['tar', '-xOf', str(archive), 'python/PYTHON.json']))
    if metadata['python_version'] != pins['python_version'] or metadata['target_triple'] != pins['target_triple']:
        raise RuntimeError('Unexpected Python distribution metadata')
    members = subprocess.check_output(['tar', '-tf', str(archive)], text=True).splitlines()
    files = []
    for member in members:
        path = PurePosixPath(member)
        if path.parent != PurePosixPath('python/licenses') or not path.name.startswith('LICENSE'):
            continue
        target = notices / path.name
        target.write_bytes(subprocess.check_output(['tar', '-xOf', str(archive), member]))
        files.append(str(target.relative_to(base)))
    if not files:
        raise RuntimeError('Python distribution has no third-party notices')
    recipe = next(x for x in pins['archives'] if x['role'] == 'build-recipes')
    with tarfile.open(cache / recipe['filename']) as tar:
        member = next(x for x in tar if x.isfile() and PurePosixPath(x.name).name == 'LICENSE')
        target = notices / 'LICENSE.python-build-standalone.txt'
        target.write_bytes(tar.extractfile(member).read())
        files.append(str(target.relative_to(base)))
    (cache / 'PYTHON.json').write_text(json.dumps(metadata, indent=2) + '\n')
    return files, pins


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    files, pins = prepare(args.output_dir.resolve())
    print(json.dumps({'notices': len(files), 'python_version': pins['python_version']}))
