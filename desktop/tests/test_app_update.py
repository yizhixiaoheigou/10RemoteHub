"""Use only temporary fake bundles; no codesign or /Applications mutation."""
import importlib.util
from pathlib import Path
import shutil

import pytest

spec = importlib.util.spec_from_file_location('app_update', Path(__file__).resolve().parents[1]/'scripts/update_macos.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def bundles(tmp_path):
    source, installed = tmp_path/'source.app', tmp_path/'installed.app'
    source.mkdir(); installed.mkdir()
    (source/'new').write_text('new version')
    (installed/'legacy').write_text('old version')
    return source, installed


def test_update_does_not_merge_obsolete_files_and_keeps_backup(tmp_path):
    source, installed = bundles(tmp_path)
    checked = []
    backup = updater.replace_app(source, installed, copy=shutil.copytree,
                                 validate=checked.append, running=lambda _: False)
    assert (installed/'new').read_text() == 'new version'
    assert not (installed/'legacy').exists()
    assert (backup/'legacy').read_text() == 'old version'
    assert checked[0] == source and checked[-1] == installed and len(checked) == 3


def test_failed_final_verification_restores_original(tmp_path):
    source, installed = bundles(tmp_path)
    def validate(path):
        if path == installed:
            raise RuntimeError('signature rejected')
    with pytest.raises(RuntimeError, match='signature rejected'):
        updater.replace_app(source, installed, copy=shutil.copytree,
                            validate=validate, running=lambda _: False)
    assert (installed/'legacy').read_text() == 'old version'
    assert not (installed/'new').exists()


def test_running_app_cannot_be_replaced(tmp_path):
    source, installed = bundles(tmp_path)
    with pytest.raises(RuntimeError, match='先从'):
        updater.replace_app(source, installed, copy=lambda *_: pytest.fail('must not copy'),
                            validate=lambda _: None, running=lambda _: True)
    assert (installed/'legacy').exists()


def test_app_reopened_during_copy_keeps_existing_version(tmp_path):
    source, installed = bundles(tmp_path)
    states = iter([False, True])
    with pytest.raises(RuntimeError, match='重新打开'):
        updater.replace_app(source, installed, copy=shutil.copytree,
                            validate=lambda _: None, running=lambda _: next(states))
    assert (installed/'legacy').exists() and not (installed/'new').exists()


def test_old_update_copies_are_cleared_and_backup_is_not_an_app(tmp_path):
    stale = tmp_path/'.10RemoteHub-update-old'
    (stale/'previous.app').mkdir(parents=True)
    source, installed = bundles(tmp_path)
    backup = updater.replace_app(source, installed, copy=shutil.copytree,
                                 validate=lambda _: None, running=lambda _: False)
    assert not stale.exists()
    assert backup.name.endswith('.rollback')
    assert not list(tmp_path.glob('.10RemoteHub-update-*/**/*.app'))
