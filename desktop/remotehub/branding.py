"""Central display names for 10RemoteHub.

Protocol, storage IDs and hardware IDs deliberately stay stable when renamed.
"""
import json
from pathlib import Path
BRAND=json.loads(Path(__file__).with_name("branding.json").read_text(encoding="utf-8"))
APP_NAME=BRAND["product_name"]
