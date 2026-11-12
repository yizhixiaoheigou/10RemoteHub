"""Signed update manifest: only our key can produce an installable release."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from remotehub import updates

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='update channel ships macOS .app bundles only')


def keypair(tmp_path):
    private, public = tmp_path / 'k.pem', tmp_path / 'pub.pem'
    subprocess.run(['/usr/bin/openssl', 'genrsa', '-out', str(private), '2048'],
                   check=True, capture_output=True)
    subprocess.run(['/usr/bin/openssl', 'rsa', '-in', str(private), '-pubout', '-out', str(public)],
                   check=True, capture_output=True)
    return private, public


def manifest(version='0.2.0', build='2611060200', arch='arm64', payload=b'zip'):
    return {
        'schema': 1, 'version': version, 'build': build, 'notes': '修了一些问题',
        'assets': {arch: {'name': f'10RemoteHub-{version}-{build}-{arch}.zip',
                          'url': f'https://example.invalid/{arch}.zip',
                          'sha256': hashlib.sha256(payload).hexdigest(),
                          'size': len(payload)}},
    }


def signed(tmp_path, private, data):
    path = tmp_path / 'latest.json'
    path.write_bytes(json.dumps(data).encode())
    sig = tmp_path / 'latest.json.sig'
    subprocess.run(['/usr/bin/openssl', 'dgst', '-sha256', '-sign', str(private),
                    '-out', str(sig), str(path)], check=True, capture_output=True)
    return path.read_bytes(), sig.read_bytes()


def test_manifest_verifies_and_tampering_is_rejected(tmp_path):
    private, public = keypair(tmp_path)
    raw, signature = signed(tmp_path, private, manifest())
    updates.verify_manifest(raw, signature, public)
    with pytest.raises(updates.UpdateError):
        updates.verify_manifest(raw.replace(b'0.2.0', b'0.2.1'), signature, public)
    with pytest.raises(updates.UpdateError):
        updates.verify_manifest(raw, b'', public)


def test_parse_manifest_reads_assets(tmp_path):
    private, _ = keypair(tmp_path)
    raw, _ = signed(tmp_path, private, manifest())
    update = updates.parse_manifest(raw)
    assert update.version == '0.2.0' and update.build == '2611060200'
    assert update.assets['arm64'].size == 3


@pytest.mark.parametrize('remote,local,expected', [
    (('0.2.0', '1'), ('0.1.0', '9'), True),
    (('0.1.0', '10'), ('0.1.0', '9'), True),
    (('0.1.0', '9'), ('0.1.0', '9'), False),
    (('0.1.0', '8'), ('0.1.0', '9'), False),
    (('0.10.0', '1'), ('0.9.0', '9'), True),
])
def test_is_newer(remote, local, expected):
    assert updates.is_newer(remote[0], remote[1], local[0], local[1]) is expected


def test_check_returns_only_newer_and_verifies(tmp_path):
    private, public = keypair(tmp_path)
    raw, signature = signed(tmp_path, private, manifest())

    def opener(url, timeout=0):
        class Response:
            def __init__(self, data): self.data = data
            def read(self, size=-1): return self.data
            def __enter__(self): return self
            def __exit__(self, *args): return False
        return Response(signature if url.endswith('.sig') else raw)

    found = updates.check(url='https://example.invalid/latest.json', local_version='0.1.0', local_build='1', arch='arm64', opener=opener, key=public)
    assert found and found.version == '0.2.0'
    assert updates.check(url='https://example.invalid/latest.json', local_version='0.2.0', local_build='999999999999',
                         arch='arm64', opener=opener, key=public) is None
    with pytest.raises(updates.UpdateError):
        updates.check(url='https://example.invalid/latest.json', local_version='0.1.0', local_build='1', arch='x86_64', opener=opener, key=public)


def test_download_rejects_wrong_checksum(tmp_path):
    asset = updates.Asset(name='x.zip', url='https://example.invalid/x.zip',
                          sha256=hashlib.sha256(b'expected').hexdigest())

    def opener(url, timeout=0):
        class Response:
            def __init__(self): self.sent = False
            def read(self, size=-1):
                if self.sent:
                    return b''
                self.sent = True
                return b'tampered'
            def __enter__(self): return self
            def __exit__(self, *args): return False
        return Response()

    with pytest.raises(updates.UpdateError):
        updates.download(asset, tmp_path / 'x.zip', opener=opener)


def test_install_script_swaps_and_restores(tmp_path):
    source, destination = tmp_path / 'new.app', tmp_path / 'Applications/10RemoteHub.app'
    source.mkdir(); destination.mkdir(parents=True)
    (destination / 'old').write_text('old')
    script = updates.install_script(source, destination, 999999, tmp_path / 'backup.app',
                                    opener='/usr/bin/true')
    path = tmp_path / 'install.sh'
    path.write_text(script)
    subprocess.run(['/bin/sh', '-n', str(path)], check=True)
    result = subprocess.run(['/bin/sh', str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert destination.is_dir() and not (destination / 'old').exists()
    assert not (tmp_path / 'backup.app').exists()


def test_install_script_restores_previous_app_when_copy_fails(tmp_path):
    destination = tmp_path / 'Applications/10RemoteHub.app'
    destination.mkdir(parents=True)
    (destination / 'previous-version').write_text('keep this app')
    backup = tmp_path / 'backup.app'
    script = updates.install_script(tmp_path / 'missing-source.app', destination,
                                    999999, backup, opener='/usr/bin/true')
    path = tmp_path / 'rollback.sh'; path.write_text(script)
    result = subprocess.run(['/bin/sh', str(path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert (destination / 'previous-version').read_text() == 'keep this app'
    assert not backup.exists()


def test_update_install_uses_unique_private_backup(qapp, tmp_path, monkeypatch):
    from remotehub.ui.window import MainWindow

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    window = MainWindow(tmp_path / 'config', safe=True)
    staged = []

    def stage(_, workdir):
        staged.append(workdir)
        app = workdir / '10RemoteHub.app'
        app.mkdir()
        return app

    calls = []
    monkeypatch.setattr(updates, 'stage_update', stage)
    monkeypatch.setattr(updates, 'verify_app', lambda *_: None)
    monkeypatch.setattr(subprocess, 'Popen', lambda cmd, **kwargs: calls.append(cmd))
    window.quit_app = lambda: None
    script = None
    try:
        window.install_downloaded_update(tmp_path / 'update.zip')
        script = Path(calls[0][1])
        contents = script.read_text()
        assert len(staged) == 1 and staged[0].name.startswith('staged-')
        assert staged[0].parent == home / 'Library/Caches/RemoteHub/updates'
        assert str(staged[0] / 'previous.app') in contents
        assert '/tmp/10RemoteHub-previous.app' not in contents
    finally:
        window.shutdown()
        if script is not None:
            script.unlink(missing_ok=True)
            script.parent.rmdir()
