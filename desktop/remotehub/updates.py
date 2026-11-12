"""Signed update manifest: check, download, verify, hand off to a small shell updater.

The manifest is a JSON file plus an RSA-SHA256 signature made with a key that
never ships. Verifying it with the bundled public key means a compromised
download mirror or GitHub account cannot install a different build.
"""
from dataclasses import dataclass
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import tempfile
import urllib.request
import urllib.parse

# Source snapshots have no default release channel. Maintainers can explicitly
# configure a signed manifest once their own release channel is ready.
MANIFEST_URL = os.environ.get("REMOTEHUB_UPDATE_URL", "")
PUBLIC_KEY = Path(__file__).with_name("update-public.pem")
OPENSSL = "/usr/bin/openssl"
CERTIFICATE_SHA1 = "C4A264B1660250621FF367B91547E1DA5D905FD6"
MINIMUM_INTERVAL = 24 * 3600
MAX_MANIFEST_BYTES = 1 << 20
MAX_DOWNLOAD_BYTES = 512 << 20


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    sha256: str
    size: int = 0


@dataclass(frozen=True)
class Update:
    version: str
    build: str
    notes: str
    assets: dict  # arch -> Asset


class UpdateError(RuntimeError):
    pass


def parse_manifest(raw: bytes) -> Update:
    try:
        data = json.loads(raw.decode("utf-8"))
        assets = {str(arch): Asset(name=str(item["name"]), url=str(item["url"]),
                                   sha256=str(item["sha256"]).lower(), size=int(item.get("size", 0)))
                  for arch, item in data["assets"].items()}
        for asset in assets.values():
            validate_asset(asset)
        return Update(version=str(data["version"]), build=str(data["build"]),
                      notes=str(data.get("notes", "")), assets=assets)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise UpdateError("更新清单格式不正确") from exc


def validate_asset(asset):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip", asset.name)
            or not re.fullmatch(r"[a-f0-9]{64}", asset.sha256)
            or type(asset.size) is not int or not 0 <= asset.size <= MAX_DOWNLOAD_BYTES
            or urllib.parse.urlsplit(asset.url).scheme != "https"
            or not urllib.parse.urlsplit(asset.url).hostname):
        raise UpdateError("更新包名称、地址、大小或校验值无效")


def verify_manifest(raw: bytes, signature: bytes, key: Path = PUBLIC_KEY) -> None:
    """Raises UpdateError unless signature matches raw bytes with the bundled key."""
    if not signature:
        raise UpdateError("更新清单缺少签名")
    with tempfile.TemporaryDirectory(prefix="rh-update-") as temporary:
        base = Path(temporary)
        manifest, sig = base / "latest.json", base / "latest.json.sig"
        manifest.write_bytes(raw)
        sig.write_bytes(signature)
        result = subprocess.run([OPENSSL, "dgst", "-sha256", "-verify", str(key),
                                 "-signature", str(sig), str(manifest)],
                                capture_output=True, text=True)
    if result.returncode != 0 or "Verified OK" not in result.stdout:
        raise UpdateError("更新清单签名校验失败")


def is_newer(remote_version: str, remote_build: str, local_version: str, local_build: str) -> bool:
    def parts(text):
        return tuple(int(piece) if piece.isdigit() else 0 for piece in text.split("."))
    remote, local = parts(remote_version), parts(local_version)
    length = max(len(remote), len(local))
    remote += (0,) * (length - len(remote))
    local += (0,) * (length - len(local))
    if remote != local:
        return remote > local
    try:
        return int(remote_build) > int(local_build)
    except ValueError:
        return remote_build > local_build


def pick_asset(update: Update, arch: str) -> Asset:
    asset = update.assets.get(arch)
    if asset is None:
        raise UpdateError(f"这个版本没有 {arch} 的安装包")
    return asset


def fetch(url: str, opener=urllib.request.urlopen, timeout=20) -> bytes:
    with opener(url, timeout=timeout) as response:
        data = response.read(MAX_MANIFEST_BYTES + 1)
        if len(data) > MAX_MANIFEST_BYTES:
            raise UpdateError("更新清单超过大小限制")
        return data


def check(url: str = MANIFEST_URL, local_version: str = "", local_build: str = "",
          arch: str = "arm64", opener=urllib.request.urlopen, key: Path = PUBLIC_KEY) -> Update | None:
    """Return the newer release for this architecture, or None."""
    if not url.strip():
        raise UpdateError("当前版本尚未配置更新来源；请查看项目发布说明。")
    try:
        raw = fetch(url, opener=opener)
        signature = fetch(url + ".sig", opener=opener)
    except Exception as exc:  # network, 404, DNS
        raise UpdateError("无法获取更新信息：" + str(exc)) from exc
    verify_manifest(raw, signature, key)
    update = parse_manifest(raw)
    if not is_newer(update.version, update.build, local_version, local_build):
        return None
    pick_asset(update, arch)
    return update


def download(asset: Asset, destination: Path, opener=urllib.request.urlopen, chunk=1 << 20) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    validate_asset(asset)
    fd, name = tempfile.mkstemp(prefix=".rh-download-", dir=destination.parent)
    partial = Path(name)
    total = 0
    try:
        with os.fdopen(fd, "wb") as handle, opener(asset.url, timeout=60) as response:
            while True:
                block = response.read(chunk)
                if not block:
                    break
                total += len(block)
                if total > (asset.size or MAX_DOWNLOAD_BYTES):
                    raise UpdateError("下载的文件超过大小限制")
                digest.update(block)
                handle.write(block)
        if digest.hexdigest() != asset.sha256 or (asset.size and total != asset.size):
            raise UpdateError("下载的文件校验不通过")
        partial.replace(destination)
        return destination
    finally:
        partial.unlink(missing_ok=True)


INSTALL_SCRIPT = """#!/bin/sh
# Wait for the App to exit, swap bundles, restore on failure, then reopen.
source={source}
destination={destination}
backup={backup}
while /bin/kill -0 {pid} 2>/dev/null; do /bin/sleep 0.5; done
/bin/rm -rf "$backup"
if [ -d "$destination" ]; then
    /bin/mv "$destination" "$backup" || exit 1
fi
if /usr/bin/ditto "$source" "$destination"; then
    /usr/bin/xattr -dr com.apple.quarantine "$destination" 2>/dev/null || :
    {opener} "$destination"
    /bin/rm -rf "$backup"
else
    /bin/rm -rf "$destination"
    [ -d "$backup" ] && /bin/mv "$backup" "$destination"
    {opener} "$destination"
    exit 1
fi
"""


def install_script(source: Path, destination: Path, pid: int, backup: Path,
                   opener: str = "/usr/bin/open") -> str:
    return INSTALL_SCRIPT.format(source=shlex.quote(str(source)), destination=shlex.quote(str(destination)), pid=int(pid),
                                 backup=shlex.quote(str(backup)), opener=shlex.quote(opener))


def stage_update(archive: Path, workdir: Path) -> Path:
    """Unpack the zip and return the App inside it."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["/usr/bin/ditto", "-x", "-k", str(archive), str(workdir)],
                            capture_output=True, text=True)
    if result.returncode:
        raise UpdateError("解压更新包失败：" + result.stderr.strip())
    apps = [path for path in workdir.iterdir() if path.suffix == ".app"]
    if len(apps) != 1:
        raise UpdateError("更新包里没有唯一的 App")
    return apps[0]


def verify_app(app: Path, certificate_sha1: str) -> None:
    """The unpacked App must carry our own signing certificate."""
    result = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                            capture_output=True, text=True)
    if result.returncode:
        raise UpdateError("更新包的签名无效")
    with tempfile.TemporaryDirectory(prefix="rh-cert-") as temporary:
        prefix = Path(temporary) / "cert"
        subprocess.run(["/usr/bin/codesign", "-d", f"--extract-certificates={prefix}", str(app)],
                       capture_output=True)
        leaf = Path(f"{prefix}0")
        if not leaf.is_file():
            raise UpdateError("更新包没有签名证书")
        actual = hashlib.sha1(leaf.read_bytes()).hexdigest().upper()
    if actual != certificate_sha1.upper():
        raise UpdateError("更新包不是用本项目证书签名的")
