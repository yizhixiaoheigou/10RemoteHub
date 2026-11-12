"""Fetch hash-pinned source archives and collect macOS release notices.

Run inventory_macos_runtime.py first. This prepares evidence; native package
validation and legal/source delivery review remain separate.
"""
import base64,hashlib,json,os,re,shutil,sys,tarfile,tempfile,urllib.request,argparse
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=ROOT/'artifacts/release-materials')
BASE=parser.parse_args().output_dir.resolve();BASE.mkdir(parents=True,exist_ok=True)
OUT=BASE/'notices';OUT.mkdir(exist_ok=True)
components=[]

def extract(archive,name,qt=False):
    target=OUT/name;target.mkdir(exist_ok=True)
    result=[];referenced=set();members=set()
    modules={'qtbase','qtdeclarative','qtmultimedia','qtimageformats','qtsvg','qtshadertools','qttranslations'}
    def included(path):
        parts=PurePosixPath(path).parts
        return not qt or (len(parts)>1 and parts[1] in modules and not {'examples','tests'} & set(parts))
    def copy(tar,member):
        # Preserve archive-relative paths and attribution links; no extractall/symlinks.
        relative=PurePosixPath(member.name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe archive path')
        dest=target.joinpath(*relative.parts);dest.parent.mkdir(parents=True,exist_ok=True)
        data=tar.extractfile(member).read();dest.write_bytes(data)
        result.append(os.path.relpath(dest,BASE))
        return data
    with tarfile.open(archive,'r|*') as tar:
        for member in tar:
            if not member.isfile() or not included(member.name):continue
            leaf=PurePosixPath(member.name).name
            if re.match(r'^(license|licence|copying|copyright|notice|authors)([._-]|$)',leaf,re.I) or leaf=='qt_attribution.json':
                data=copy(tar,member);members.add(member.name)
                if leaf=='qt_attribution.json':
                    entries=json.loads(data, strict=False)
                    if isinstance(entries,dict):entries=[entries]
                    for entry in entries:
                        files=entry.get('LicenseFile',[])
                        if isinstance(files,str):files=[files]
                        for file in files:
                            referenced.add(os.path.normpath(str(PurePosixPath(member.name).parent/file)))
    if referenced-members:
        with tarfile.open(archive,'r|*') as tar:
            for member in tar:
                if member.isfile() and member.name in referenced-members:
                    copy(tar,member);members.add(member.name)
        missing=referenced-members
        if missing:raise RuntimeError('Missing attribution license files: '+repr(sorted(missing)))
    return result

def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1<<20),b''):digest.update(chunk)
    return digest.hexdigest()

pinned=json.loads((ROOT/'desktop/licenses/macos-sources.json').read_text())['archives']
source_dir=BASE/'sources';source_dir.mkdir(exist_ok=True)
for item in pinned:
    destination=source_dir/item['filename']
    if destination.exists():
        if sha256(destination)!=item['sha256']:raise RuntimeError('Existing source checksum mismatch: '+str(destination))
    else:
        fd,temporary=tempfile.mkstemp(prefix='.source-',dir=source_dir)
        try:
            with os.fdopen(fd,'wb') as out,urllib.request.urlopen(item['url'],timeout=60) as response:
                total=0
                while chunk:=response.read(1<<20):
                    total+=len(chunk)
                    if total>item['size']:raise RuntimeError('Source exceeds pinned size: '+item['filename'])
                    out.write(chunk)
            if sha256(Path(temporary))!=item['sha256']:raise RuntimeError('Downloaded source checksum mismatch: '+item['filename'])
            Path(temporary).replace(destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
    print('Source verified:',item['filename'],flush=True)
native=json.loads((BASE/'native-inventory.json').read_text())
if native['qt']!='6.12.0' or native['pyside']!='6.12.0' or not native['python'].startswith('3.12.13'):
    raise RuntimeError('Runtime differs from pinned source baseline; review sources before building')
if native['helper_libusb']['receipt']['source']['versions']['stable']!='1.0.29':
    raise RuntimeError('Helper libusb differs from pinned source baseline')
if not native['ffmpeg']:
    raise RuntimeError('No FFmpeg runtime provenance found')
for runtime in native['ffmpeg']:
    if ('--prefix=/usr/local/FFmpeg-n9.0.1' not in runtime['configuration']
            or '--enable-gpl' in runtime['configuration']
            or '--enable-nonfree' in runtime['configuration']
            or 'LGPL' not in runtime['license']):
        raise RuntimeError('FFmpeg differs from reviewed source/license baseline')
catalog=[item for item in pinned if item['name'] not in ('qt','pyside6','ffmpeg')]
for item in catalog:
    files=extract(BASE/'sources'/item['filename'],item['name'])
    row={'name':item['name'],'version':item['version'],'source_url':item['url'],'source_sha256':item['sha256'],'license_files':files,
         'build_notes':'Official source archive; dependency binary and build provenance are recorded in the native inventory. Rebuild instructions are in desktop/RELEASE.md.'}
    components.append(row)
qt_archive=source_dir/'qt-everywhere-src-6.12.0.tar.xz'
qt_hash=sha256(qt_archive)
assert qt_hash==base64.b64decode('mP9PRLrG7D4eYu4qQxauDj0VutsBXXU8wCaKINtS8WU=').hex()
components.append({'name':'qt','version':'6.12.0','source_url':'https://download.qt.io/official_releases/qt/6.12/6.12.0/single/'+qt_archive.name,
 'source_sha256':qt_hash,'license_files':extract(qt_archive,'qt',qt=True),'license_root':'notices/qt',
 'build_notes':'Qt 6.12.0, qVersion confirmed on the target Mac. Distributed by official PySide6 6.12.0 universal2 wheels. Only the reviewed Widgets/Multimedia runtime and its transitive modules are bundled. Complete upstream sources include configure/CMake files; binary rebuild equivalence has not been claimed.'})
vendor=ROOT/'desktop/licenses/vendor'
upstream=json.loads((vendor/'SOURCES.json').read_text())['upstream_archives']
for item in upstream:
    names=['pyside6','pyside6-addons','pyside6-essentials','shiboken6'] if item['name']=='pyside6' else ['ffmpeg']
    for name in names:
        row={'name':name,'version':item['version'],'source_url':item['source_url'],'source_sha256':item['source_sha256'],
             'license_files':[os.path.relpath(vendor/n['path'],BASE) for n in item['notices']],
             'build_notes':'Official PySide6 6.12.0 wheel; upstream pyside-setup archive contains the binding generator, build system and sources. The project uses dynamic libraries without source patches.'}
        if name=='ffmpeg':
            native=json.loads((BASE/'native-inventory.json').read_text())['ffmpeg'][0]
            row['build_notes']='Loaded target binary reports LGPL-2.1-or-later, FFmpeg n9.0.1. Configuration: '+native['configuration']+'. Official 9.0.1 source includes configure/build files. No GPL/nonfree switches enabled.'
        components.append(row)
# The installed Python also carries its aggregate license document.
python_notice=Path(sys.base_prefix)/'lib/python3.12/LICENSE.txt'
if python_notice.is_file():
    dest=OUT/'python-runtime-LICENSE.txt';shutil.copy2(python_notice,dest)
    next(c for c in components if c['name']=='python')['license_files'].append(os.path.relpath(dest,BASE))
from prepare_python_standalone import prepare
python_notices, python_provenance = prepare(BASE)
python_component = next(c for c in components if c['name']=='python')
python_component['license_files'].extend(python_notices)
python_component['runtime_provenance'] = python_provenance
python_component['build_notes'] = ('CPython 3.12.13 from python-build-standalone 20260325, aarch64-apple-darwin. '
    'The pinned build-recipes archive includes distribution patches, build scripts and hashes of third-party sources. '
    'Runtime distribution archives and recipe hashes are recorded in runtime_provenance. '
    'uv adjusts the libpython install name and signature; these do not imply a source modification.')
helper=next(c for c in components if c['name']=='libusb-helper')
helper['build_notes']='Native helper uses the existing Homebrew libusb 1.0.29 bottle; receipt records no runtime dependencies. Build with upstream configure and make, then set RH_LIBUSB_PREFIX for build_device_helper.py. Project only changes the copied Mach-O install name and code signature.'
next(c for c in components if c['name']=='libusb')['build_notes']='Runtime libusb 1.0.30 comes from libusb-package 1.0.30.0; dynamically loaded by PyUSB. Rebuild upstream libusb and point the package loader at a compatible dylib.'
path=BASE/'license-supplement-macos.json';path.write_text(json.dumps({'components':components},indent=2)+'\n')
print(json.dumps({'supplement':str(path),'components':len(components),'notices':sum(len(c['license_files']) for c in components),'qt_sha256':qt_hash}),flush=True)
