"""Release gates run without installing drivers or inspecting live devices."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import zipfile
import pytest
from remotehub import updates

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from release_policy import validate_names, verify, verify_licenses
from collect_licenses import normalize, notice_files, collect


@pytest.mark.parametrize('path', [
    'app/Contents/Frameworks/QtVirtualKeyboard.framework/Versions/A/QtVirtualKeyboard',
    '_internal/PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
    'app/PySide6/plugins/imageformats/libqpdf.dylib',
    '_internal/PySide6/QtCharts.dll',
    '_internal/PySide6/Qt6Unknown.dll',
])
def test_forbidden_and_unreviewed_modules_rejected(path):
    assert validate_names([path])


def test_essential_modules_allowed():
    assert validate_names(['app/QtCore.framework/Versions/A/QtCore',
                           'app/Qt6Gui.dll', 'app/libQt6Widgets.so.6']) == []


def test_original_style_release_with_only_generic_license_is_rejected(tmp_path):
    archive = tmp_path / 'old.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('10RemoteHub.app/Contents/Resources/licenses/THIRD_PARTY_NOTICES.txt', 'not enough')
    with pytest.raises(RuntimeError, match='components.json'):
        verify(archive)


def test_empty_or_changed_license_inventory_rejected():
    data = {'components':[{'name':'qt', 'version':'6.12.0', 'licenses':[
        {'path':'qt/LICENSE', 'sha256':'0'*64}]}]}
    files = {'components.json':json.dumps(data).encode(), 'qt/LICENSE':b'tampered'}
    errors = verify_licenses(files.__getitem__, set(files), '')
    assert any('Missing/changed notice' in e for e in errors)
    assert any('source/build evidence' in e for e in errors)


def test_distribution_name_and_pep639_notices(tmp_path):
    assert normalize('PySide6_Addons') == 'pyside6-addons'
    class Distribution:
        files = ['pyside6_addons-6.12.0.dist-info/licenses/LICENSE.txt', 'module.py',
                 'PyObjCTest/copying.cpython-312-darwin.so', 'package/copying.py']
        def locate_file(self, file): return tmp_path / file
    dist = Distribution()
    path = dist.locate_file(dist.files[0]); path.parent.mkdir(parents=True)
    path.write_text('fixture license')
    for name in dist.files[2:]:
        binary = dist.locate_file(name); binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b'compiled module, not a license')
    assert list(notice_files(dist)) == [path]


def test_collection_fails_on_missing_components_and_preserves_previous_evidence(tmp_path):
    out = tmp_path / 'licenses'
    with pytest.raises(RuntimeError, match='Required distribution not installed'):
        collect(out, distributions=[])
    assert (out / 'PROJECT-LICENSE.txt').is_file()
    with pytest.raises(FileExistsError):
        collect(out, distributions=[])


def test_collected_attribution_keeps_relative_license_links(tmp_path, monkeypatch):
    import collect_licenses
    monkeypatch.setattr(collect_licenses, 'BUNDLED', set())
    tree = tmp_path / 'upstream'
    (tree / 'module').mkdir(parents=True)
    (tree / 'LICENSE').write_text('Original third-party copyright and permission')
    (tree / 'module/qt_attribution.json').write_text(json.dumps({'LicenseFile': '../LICENSE'}))
    rows = [{'name': name, 'version': '1.0', 'license_root': 'upstream',
             'license_files': ['upstream/LICENSE', 'upstream/module/qt_attribution.json'],
             'source_url': 'https://example.invalid/source.tar.gz',
             'source_sha256': 'a' * 64, 'build_notes': 'Test fixture'}
            for name in ('qt', 'ffmpeg', 'python', 'libusb')]
    supplement = tmp_path / 'supplement.json'
    supplement.write_text(json.dumps({'components': rows}))
    output = collect(tmp_path / 'licenses', supplement, distributions=[], platform='win32')
    attribution, = (output / 'qt').rglob('qt_attribution.json')
    linked = attribution.parent / json.loads(attribution.read_text())['LicenseFile']
    assert linked.read_text() == (tree / 'LICENSE').read_text()


def test_runtime_hook_dependency_is_covered_without_inventing_shared_qt_modules(tmp_path):
    from collect_licenses import runtime_distributions
    site = tmp_path / 'site-packages'
    site.mkdir()
    for name in ('qt_init.py', 'packaging.py', 'unused_pdf.py'):
        (site / name).write_text('# fixture')
    class Distribution:
        def __init__(self, files): self.files = files
        def locate_file(self, file): return site / file
    installed = {'pyside6': Distribution(['qt_init.py']),
                 'pyside6-pdf': Distribution(['qt_init.py', 'unused_pdf.py']),
                 'packaging': Distribution(['packaging.py'])}
    analysis = tmp_path / 'Analysis-00.toc'
    analysis.write_text(repr([('PySide6', str(site / 'qt_init.py'), 'PYMODULE'),
                              ('packaging', str(site / 'packaging.py'), 'PYMODULE')]))
    assert runtime_distributions(analysis, installed, {'pyside6'}) == {'packaging'}


@pytest.mark.parametrize('name,url,size', [('../x.zip','https://example.invalid/x',1),
    ('x.zip','file:///tmp/x',1), ('x.zip','https://example.invalid/x',-1),
    ('x.zip','https://example.invalid/x',updates.MAX_DOWNLOAD_BYTES+1)])
def test_unsafe_update_asset_is_rejected(name, url, size):
    with pytest.raises(updates.UpdateError):
        updates.validate_asset(updates.Asset(name,url,'a'*64,size))


def test_oversized_download_cleans_only_its_private_temp_file(tmp_path):
    existing = tmp_path / 'old.zip'; existing.write_bytes(b'old')
    other = tmp_path / 'old.zip.part'; other.write_bytes(b'user data')
    asset = updates.Asset('new.zip','https://example.invalid/x',hashlib.sha256(b'xx').hexdigest(),1)
    with pytest.raises(updates.UpdateError, match='大小限制'):
        updates.download(asset, existing, opener=lambda *a,**kw:io.BytesIO(b'xx'))
    assert existing.read_bytes() == b'old' and other.read_bytes() == b'user data'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['old.zip', 'old.zip.part']


def test_bounded_manifest_fetch():
    with pytest.raises(updates.UpdateError, match='大小限制'):
        updates.fetch('https://example.invalid',opener=lambda *a,**kw:io.BytesIO(
            b'x'*(updates.MAX_MANIFEST_BYTES+1)))


import subprocess

def test_updater_paths_are_literal_shell_data(tmp_path):
    if not Path('/bin/sh').exists():
        pytest.skip('POSIX updater syntax test')
    marker = tmp_path/'injected'
    source = tmp_path/('a"$(touch '+str(marker).replace('/', '${IFS}')+')`false`.app')
    script = updates.install_script(source,tmp_path/'dest',999999,tmp_path/'backup')
    p=tmp_path/'script.sh';p.write_text(script)
    subprocess.run(['/bin/sh','-n',str(p)],check=True)
    # Inspect only assignments, so no copy/remove/install command can run.
    assignments='\n'.join(line for line in script.splitlines() if line.startswith(('source=','destination=','backup=')))
    result=subprocess.run(['/bin/sh','-c',assignments+'\nprintf "%s" "$source"'],capture_output=True,text=True,check=True)
    assert result.stdout == str(source) and not marker.exists()


def test_public_export_preserves_notices_and_excludes_private_history(tmp_path):
    from export_source import export
    output = tmp_path / 'candidate'
    result = export(output)
    assert not result['published'] and not (output / '.git').exists()
    assert not (output / 'DEVELOPMENT.md').exists()
    assert not (output / 'artifacts').exists()
    assert not (output / 'desktop/remotehub/ico.py').exists()
    vendor = output / 'desktop/licenses/vendor'
    sources = json.loads((vendor / 'SOURCES.json').read_text())
    for archive in sources['upstream_archives']:
        for notice in archive['notices']:
            assert hashlib.sha256((vendor / notice['path']).read_bytes()).hexdigest() == notice['sha256']
    with pytest.raises(FileExistsError):
        export(output)


def test_mac_requires_separate_helper_libusb_inventory():
    # Homebrew helper libusb and the Python wheel can have different versions.
    files = {'components.json':json.dumps({'platform':'darwin','components':[
        {'name':'libusb','version':'1.0.30','licenses':[]}]}).encode()}
    errors = verify_licenses(files.__getitem__, set(files), '')
    assert 'Missing native component inventory: libusb-helper' in errors


def test_source_archive_has_no_local_file_metadata(tmp_path):
    import os
    import tarfile
    from export_source import write_archive
    root = tmp_path / 'source'; root.mkdir()
    file = root / 'run.sh'; file.write_bytes(b'echo example\n')
    file.chmod(0o755); os.utime(file, (1234567890, 1234567890))
    inventory = {'files': [{'path': 'run.sh', 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}]}
    (root / 'SOURCE-INVENTORY.json').write_text(json.dumps(inventory))
    archive = tmp_path / 'source.tar.gz'
    write_archive(root, archive)
    with tarfile.open(archive) as tar:
        entries = tar.getmembers()
        assert {x.name for x in entries} == {'10RemoteHub/run.sh', '10RemoteHub/SOURCE-INVENTORY.json'}
        assert all((x.uid, x.gid, x.uname, x.gname, x.mtime, x.pax_headers) == (0, 0, '', '', 0, {}) for x in entries)
        assert tar.getmember('10RemoteHub/run.sh').mode == 0o755
        assert tar.extractfile('10RemoteHub/run.sh').read() == file.read_bytes()
    with pytest.raises(FileExistsError):
        write_archive(root, archive)
    (root / 'private.log').write_text('must not be archived')
    with pytest.raises(RuntimeError, match='inventory'):
        write_archive(root, tmp_path / 'unsafe.tar.gz')


def test_windows_personal_path_rejected_before_source_export():
    from export_source import PRIVATE
    private_path = 'C:' + chr(92) + 'Users' + chr(92) + 'example-person' + chr(92) + 'file'
    assert PRIVATE.search(private_path)


def test_windows_zip_accepts_epoch_source_dates_without_carrying_local_metadata(tmp_path):
    import os
    from package_windows_zip import package
    app = tmp_path / 'app'; app.mkdir()
    file = app / 'LICENSE.txt'; file.write_bytes(b'original notice')
    os.utime(file, (0, 0))
    archive = package(app, tmp_path / 'release.zip')
    with zipfile.ZipFile(archive) as zip_file:
        info = zip_file.getinfo('LICENSE.txt')
        assert info.date_time == (1980, 1, 1, 0, 0, 0)
        assert zip_file.read(info) == b'original notice'
        assert info.comment == b''
    with pytest.raises(FileExistsError):
        package(app, archive)


def test_frozen_sysconfig_removes_local_paths_without_changing_abi_values():
    from sanitize_sysconfig import sanitize
    home = '/Users/audit-example'
    prefix = home + '/python'
    values = {'LIBDIR': prefix + '/lib', 'CFLAGS': '-I' + prefix + '/include',
              'BUILD_DIR': home + '/work/project', 'SOABI': 'cpython-312-darwin',
              'SIZEOF_VOID_P': 8}
    clean = sanitize(values, prefix, home)
    assert clean['LIBDIR'] == '/usr/local/lib'
    assert clean['CFLAGS'] == '-I/usr/local/include'
    assert clean['BUILD_DIR'] == '/opt/remotehub-build/work/project'
    assert clean['SOABI'] == values['SOABI'] and clean['SIZEOF_VOID_P'] == 8
    assert home not in repr(clean)
    assert values['LIBDIR'] == prefix + '/lib'


def test_unconfigured_updates_do_not_contact_any_server():
    with pytest.raises(updates.UpdateError, match='尚未配置'):
        updates.check(url='', opener=lambda *a, **kw: pytest.fail('Unexpected network request'))
