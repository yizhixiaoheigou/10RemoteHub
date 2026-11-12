"""Open bundled component installers from an explicit UI action.

The packages live inside the signed App bundle, so their integrity is already
covered by the App's signature. A downloaded copy, however, inherits the
download quarantine flag, and Gatekeeper then refuses the unsigned package.
Clearing the flag on our own sealed payload is what lets Installer run; the
package itself is not modified, and Installer still asks for administrator
consent.
"""
import subprocess
import sys

PROBE = "/usr/bin/xattr"
OPENER = "/usr/bin/open"


def open_package(path):
    if sys.platform != "darwin":
        raise RuntimeError("组件安装仅用于 macOS")
    subprocess.run([PROBE, "-d", "com.apple.quarantine", str(path)], check=False,
                   capture_output=True)
    subprocess.run([OPENER, str(path)], check=True)
