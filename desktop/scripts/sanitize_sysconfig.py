"""Stage CPython build metadata without embedding the builder's home directory.

Only the generated module passed to PyInstaller is changed. The interpreter and
its installed sysconfig data remain untouched. Frozen apps cannot use the
original developer's paths to build extensions in any case.
"""
import importlib
from pathlib import Path
import pprint
import sys
import sysconfig


def sanitize(values, prefix, home):
    replacements = [(str(prefix), '/usr/local'), (str(home), '/opt/remotehub-build')]
    result = {}
    for key, value in values.items():
        if isinstance(value, str):
            for old, new in replacements:
                value = value.replace(old, new)
        result[key] = value
    return result


def stage(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = sysconfig._get_sysconfigdata_name()
    original = importlib.import_module(name).build_time_vars
    values = sanitize(original, sys.base_prefix, Path.home())
    path = directory / (name + '.py')
    path.write_text('# Sanitized build metadata for the frozen application.\n'
                    + 'build_time_vars = ' + pprint.pformat(values, sort_dicts=True) + '\n', encoding='utf-8')
    return directory
