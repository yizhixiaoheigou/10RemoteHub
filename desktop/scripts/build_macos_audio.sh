#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
out="build/RemoteHubAudio.driver"
mkdir -p "$out/Contents/MacOS" "$out/Contents/Resources"
python3 - <<'PY'
import json
from pathlib import Path
b=json.loads(Path('remotehub/branding.json').read_text())
values={'RH_MIC_NAME':b['microphone_name'],'RH_FEED_NAME':b['audio_feed_name'],'RH_PRODUCT_NAME':b['product_name'],'RH_AUDIO_NAME':b['product_name']+' Audio'}
Path('build/branding.h').write_text('\n'.join('#define '+k+' '+json.dumps(v,ensure_ascii=False) for k,v in values.items())+'\n')
PY
clang -std=c11 -O2 -fblocks -bundle -arch arm64 -arch x86_64 \
  -Ibuild -mmacosx-version-min=12.0 native/macos-audio/RemoteHubAudio.c native/loopback.c \
  -framework CoreAudio -framework CoreFoundation -o "$out/Contents/MacOS/RemoteHubAudio"
cp native/macos-audio/Info.plist "$out/Contents/Info.plist"
cp native/macos-audio/LICENSE.txt "$out/Contents/Resources/LICENSE.txt"
python3 - "$out/Contents/Info.plist" <<'PY'
import json,plistlib,sys
from pathlib import Path
brand=json.loads(Path('remotehub/branding.json').read_text())
p=Path(sys.argv[1]); data=plistlib.loads(p.read_bytes()); data['CFBundleName']=brand['product_name']+' Audio';p.write_bytes(plistlib.dumps(data))
PY
codesign --force --sign "${CODESIGN_IDENTITY:--}" "$out"
clang -std=c11 -Wall -Wextra -Werror native/loopback.c native/tests/loopback_test.c -o build/loopback-test
build/loopback-test
clang -std=c11 -Wall -Wextra -Werror -arch arm64 -arch x86_64 native/tests/audio_plugin_probe.c \
  -framework CoreAudio -framework CoreFoundation -o build/audio-plugin-probe
codesign --force --sign "${CODESIGN_IDENTITY:--}" build/audio-plugin-probe
build/audio-plugin-probe "$PWD/$out"
# Build only; installation and audio-service restart are separate user actions.
python3 scripts/package_audio_component.py
printf '%s\n' "Built build/RemoteHubAudio.pkg; not installed."
