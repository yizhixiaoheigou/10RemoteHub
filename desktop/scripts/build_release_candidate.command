#!/bin/bash
# Run from the local Mac login session so codesign can use its existing keychain.
# Build only: no installation, USB takeover, repository push or publication.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${REMOTEHUB_PYTHON:-}" ]; then
    python="$REMOTEHUB_PYTHON"
elif [ -x .venv-mac/bin/python ]; then
    python="$PWD/.venv-mac/bin/python"
elif [ -x .venv/bin/python ]; then
    python="$PWD/.venv/bin/python"
else
    echo 'Create the project Python 3.12 environment first; see RELEASE.md.' >&2
    exit 1
fi
materials="${REMOTEHUB_MATERIALS:-$PWD/../artifacts/release-materials}"
"$python" scripts/inventory_macos_runtime.py --output-dir "$materials"
"$python" scripts/prepare_macos_licenses.py --output-dir "$materials"
"$python" scripts/release_macos.py --codesign-identity "${CODESIGN_IDENTITY:-10RemoteHub}" \
    --license-supplement "$materials/license-supplement-macos.json"
