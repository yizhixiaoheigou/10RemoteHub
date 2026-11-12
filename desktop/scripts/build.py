#!/usr/bin/env python3
"""Build on each target OS; bundles the runtime and userspace dependencies.

Does not install drivers, change permissions, launch the application or publish.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(); p.add_argument("--skip-audio-component",action="store_true")
p.add_argument("--dist-dir", type=Path, help="Output directory, relative to desktop/ unless absolute")
p.add_argument("--license-supplement", type=Path, required=True,
               help="Exact-version native source/notice inventory; see RELEASE.md")
signing=p.add_mutually_exclusive_group()
signing.add_argument("--codesign-identity", help="macOS signing identity; defaults to CODESIGN_IDENTITY")
signing.add_argument("--adhoc", action="store_true", help="Explicit macOS scratch build; permissions may expire after rebuild")
a=p.parse_args()
identity=None if a.adhoc else (a.codesign_identity or os.environ.get("CODESIGN_IDENTITY"))
if sys.platform=="darwin":
    if not a.adhoc and (not identity or identity.strip()=="-"):
        p.error("macOS needs --codesign-identity (or CODESIGN_IDENTITY) for persistent permissions; use --adhoc only for scratch builds")
    # The optional microphone component must use the same selected identity.
    os.environ["CODESIGN_IDENTITY"]=identity or "-"
if sys.platform not in ("darwin","win32"):
    p.error("Release builds target macOS and Windows only; Linux support is isolated under linux/")
def run(*cmd):subprocess.run([str(x) for x in cmd],check=True,cwd=ROOT)
brand=json.loads((ROOT/"remotehub/branding.json").read_text(encoding="utf-8"))
name=brand["product_name"]
target={"darwin":"macos","win32":"windows"}[sys.platform]
dist=(ROOT/(a.dist_dir or Path("dist")/target)).resolve()
run(sys.executable,"scripts/build_icons.py")
# Third-party license texts travel inside the bundle; see desktop/licenses/.
license_stage = subprocess.run([sys.executable, "scripts/collect_licenses.py", "--supplement",
    str(a.license_supplement.resolve())], cwd=ROOT, capture_output=True, text=True)
if license_stage.returncode:
    raise SystemExit(license_stage.stderr or license_stage.stdout)
extra=["--add-data",license_stage.stdout.strip()+os.pathsep+"licenses"]
# Include the complete modified LGPL decoder source and license alongside the
# frozen module. Rebuild instructions and provenance are in its NOTICE.md.
for source in sorted((ROOT / "remotehub/codec").iterdir()):
    if source.suffix in (".py", ".md") or source.name == "COPYING.LGPLv2.1":
        extra += ["--add-data", str(source)+os.pathsep+"codec-source/remotehub/codec"]
if sys.platform=="darwin":
    from sanitize_sysconfig import stage as stage_sysconfig
    extra += ['--paths', str(stage_sysconfig(ROOT / 'build/macos/frozen-sysconfig'))]
    from build_device_helper import build as build_helper
    helper_output, helper_packages = build_helper(identity)
    helper_output = helper_output.resolve()
    extra += ["--add-binary", str(helper_output/"libRemoteHubDevice.dylib")+os.pathsep+"native"]
    extra += ["--add-data", str(helper_output/"libusb-LICENSE.txt")+os.pathsep+"licenses"]
    for package in helper_packages:
        extra += ["--add-data", str(package)+os.pathsep+"components"]
    # Standalone uninstaller travels inside the bundle as a release asset too.
    run(sys.executable,"scripts/package_uninstall.py")
    extra += ["--add-data",str(ROOT/"build/RemoteHub-Uninstall.pkg")+os.pathsep+"components"]
    if not a.skip_audio_component:
        run("sh","scripts/build_macos_audio.sh")
        extra += ["--add-data",str(ROOT/"build/RemoteHubAudio.pkg")+os.pathsep+"components"]
        extra += ["--add-data",str(ROOT/"build/RemoteHubAudioComponent.pkg")+os.pathsep+"components"]
    extra += ["--osx-bundle-identifier","org.remotehub.desktop","--icon",str(ROOT/"build/macos/icons/AppIcon.icns")]
    if identity:
        # PyInstaller signs with the hardened runtime; without a TeamIdentifier the
        # bundled Python and Qt libraries fail library validation (see the plist).
        extra += ["--codesign-identity",identity,
                  "--osx-entitlements-file",str(ROOT/"native/macos-entitlements.plist")]
else:
    extra += ["--hidden-import","pynput.keyboard._win32","--icon",str(ROOT/"build/windows/icons/AppIcon.ico"),
              "--add-data",str(ROOT/"VERSION")+os.pathsep+"."]
run(sys.executable,"-m","PyInstaller","--noconfirm","--clean","--windowed","--onedir",
    "--name",name,"--distpath",dist,"--workpath",f"build/{target}/pyinstaller","--specpath",f"build/{target}",
    "--collect-all","libusb_package",
    "--additional-hooks-dir",str(ROOT/"scripts/hooks"),
    "--add-data",str(ROOT/"remotehub/assets")+os.pathsep+"remotehub/assets",
    "--add-data",str(ROOT/"remotehub/branding.json")+os.pathsep+"remotehub",
    "--add-data",str(ROOT/"remotehub/models")+os.pathsep+"remotehub/models",
    "--add-data",str(ROOT/"remotehub/update-public.pem")+os.pathsep+"remotehub",
    "--hidden-import","usb.backend.libusb1","--hidden-import","hid",
    "--exclude-module","PySide6.QtWebEngineCore","--exclude-module","PySide6.QtWebEngineWidgets",
    "--exclude-module","PySide6.QtWebEngineQuick","--exclude-module","PySide6.QtPdf",
    "--exclude-module","PySide6.QtWebSockets",
    "--exclude-module","PySide6.QtVirtualKeyboard","--exclude-module","PySide6.QtPdfWidgets",
    "--exclude-module","remotehub.ico","--exclude-module","unicorn","--exclude-module","elftools",
    "--exclude-module","pytest","--exclude-module","tkinter",*extra,"entry.py")
# Include notices for transitive Python runtime packages selected by hooks.
# This happens before the final bundle seal, and never touches installed apps.
import shutil
final_licenses = subprocess.run([sys.executable, 'scripts/collect_licenses.py', '--supplement',
    str(a.license_supplement.resolve()), '--analysis',
    str(ROOT / f'build/{target}/pyinstaller' / name / 'Analysis-00.toc')],
    cwd=ROOT, capture_output=True, text=True, check=True)
license_target = (dist / (name + '.app') / 'Contents/Resources/licenses' if sys.platform == 'darwin'
                  else dist / name / '_internal/licenses')
shutil.copytree(final_licenses.stdout.strip(), license_target, dirs_exist_ok=True)
if sys.platform=="darwin":
    # PyInstaller exposes no version flag: stamp the bundle, then re-seal it so
    # the Info.plist stays inside the code signature.
    import plistlib, time
    version=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
    build=time.strftime("%y%m%d%H%M")
    bundle=dist/(name+".app"); info_path=bundle/"Contents/Info.plist"
    info=plistlib.loads(info_path.read_bytes())
    info["CFBundleShortVersionString"]=version; info["CFBundleVersion"]=build
    info["LSMinimumSystemVersion"]="14.0"
    info_path.write_bytes(plistlib.dumps(info))
    run("codesign","--force","--sign",identity or "-","--options","runtime",
        "--entitlements",str(ROOT/"native/macos-entitlements.plist"),
        "--identifier","org.remotehub.desktop",str(bundle))
    (dist/"version.json").write_text(json.dumps({"version":version,"build":build},indent=2)+"\n",encoding="utf-8")
    run("codesign","--verify","--deep","--strict",dist/(name+".app"))
    run("codesign","--display","--requirements","-",dist/(name+".app"))
from release_policy import verify as verify_policy
verify_policy(dist/(name+".app") if sys.platform=="darwin" else dist/name)
print("Built",dist, "for",sys.platform,"; not installed or published")
manifest=ROOT.parent/"artifacts"/("dependencies-"+target+".json")
manifest.parent.mkdir(parents=True,exist_ok=True)
manifest.write_text(json.dumps({"product_name":name,"platform":sys.platform,
    "python":sys.version,"packages":sorted(
        [{"name":d.metadata["Name"],"version":d.version} for d in importlib.metadata.distributions()],
        key=lambda d:d["name"].lower())},indent=2)+"\n")
