"""Read-only macOS build provenance. Does not enumerate USB or alter audio.

Raw paths belong in the local material directory, not in a public release.
"""
import ctypes
import hashlib
import importlib.metadata as m
import json
from pathlib import Path
import platform
import subprocess
import sys
import PySide6
from PySide6.QtCore import qVersion
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=Path(__file__).resolve().parents[2]/'artifacts/release-materials')
output=parser.parse_args().output_dir.resolve();output.mkdir(parents=True,exist_ok=True)
qt=Path(PySide6.__file__).parent/'Qt'
report={'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),
        'qt':qVersion(),'pyside':PySide6.__version__,
        'packages':sorted([{'name':d.metadata['Name'],'version':d.version} for d in m.distributions()],key=lambda x:x['name'].lower())}
report['ffmpeg']=[]
for path in sorted((qt/'lib').glob('libavcodec.*.dylib')):
 lib=ctypes.CDLL(str(path))
 row={'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
 for field in ['configuration','license']:
  fn=getattr(lib,'avcodec_'+field);fn.restype=ctypes.c_char_p
  row[field]=fn().decode()
 fn=lib.avcodec_version;fn.restype=ctypes.c_uint
 v=fn();row['abi_version']='.'.join(str(n) for n in (v>>16,(v>>8)&255,v&255))
 report['ffmpeg'].append(row)
prefix=Path(subprocess.check_output(['/opt/homebrew/bin/brew','--prefix','libusb'],text=True).strip())
receipt=prefix/'INSTALL_RECEIPT.json'
report['helper_libusb']={'prefix':str(prefix),'receipt':json.loads(receipt.read_text()) if receipt.is_file() else None,
 'sha256':hashlib.sha256((prefix/'lib/libusb-1.0.dylib').read_bytes()).hexdigest()}
report['python_notice_files']=[str(p) for pattern in ('LICENSE*','lib/python*/LICENSE*','share/doc/python*/LICENSE*') for p in Path(sys.base_prefix).glob(pattern)]
path=output/'native-inventory.json'
path.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'report':str(path),'python':platform.python_version(),'qt':report['qt'],'ffmpeg':report['ffmpeg'],'libusb_source':report['helper_libusb']['receipt'].get('source',{})}))
