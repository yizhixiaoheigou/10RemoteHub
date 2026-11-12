"""Device model registry: identity rules plus what the remote looks like and reports.

Each JSON file under models/ describes one remote:
  identity      vid/pid, optional bcdDevice and serial prefix
  presentation  canvas, illustration, hit regions (source pixels)
  behavior      keymap file with the HID triggers
  voice         capability placeholder until the voice-key question is decided

A device only counts as "adapted" when a model matches it exactly; a known
dongle with an unknown bcd/serial is reported as a different remote instead of
being silently treated as the existing model.
"""
from dataclasses import dataclass
import json
from pathlib import Path

DIRECTORY = Path(__file__).parent / "models"


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    transport: str
    vendor: int
    product: int
    bcd_device: int | None
    serial_prefix: str
    canvas: tuple
    image: str
    regions: tuple
    keymap: str
    voice: dict
    schema: int = 1

    @property
    def pair(self):
        return self.vendor, self.product


def load(directory=DIRECTORY):
    models = []
    for path in sorted(Path(directory).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            identity = data["identity"]
            presentation = data.get("presentation", {})
            models.append(Model(
                id=str(data["id"]),
                name=str(data.get("name", data["id"])),
                transport=str(data.get("transport", "usb-receiver")),
                vendor=int(identity["vendor"]),
                product=int(identity["product"]),
                bcd_device=identity.get("bcd_device"),
                serial_prefix=str(identity.get("serial_prefix", "")),
                canvas=tuple(presentation.get("canvas", (793, 1983))),
                image=str(presentation.get("image", "")),
                regions=tuple(tuple(region) for region in presentation.get("regions", ())),
                keymap=str(data.get("behavior", {}).get("keymap", "")),
                voice=dict(data.get("voice", {})),
                schema=int(data.get("schema", 1)),
            ))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue  # a broken pack must not take the app down
    return models


def by_pair(vendor, product, models=None):
    for model in (models if models is not None else load()):
        if model.pair == (vendor, product):
            return model
    return None


def supported_pairs(models=None):
    return {model.pair for model in (models if models is not None else load())}


def fingerprint(device):
    """Stable, human-readable identity for logs and adaptation reports."""
    parts = [f"USB {device.vendor:04X}:{device.product:04X}"]
    bcd = getattr(device, "bcd_device", None)
    if bcd is not None:
        parts.append(f"bcd {bcd:04X}")
    serial = getattr(device, "serial", "") or ""
    if serial:
        parts.append("serial " + serial.split("_")[0])
    return " · ".join(parts)


def match(device, models=None):
    """The one model that claims this device, or None."""
    for model in (models if models is not None else load()):
        if model.pair != (device.vendor, device.product):
            continue
        # bcdDevice is the firmware build: a different one cannot be assumed to
        # share this key table. The serial identifies a unit, not a model, so it
        # is recorded in the fingerprint but never used to reject a device.
        bcd = getattr(device, "bcd_device", None)
        if model.bcd_device is not None and bcd is not None and bcd != model.bcd_device:
            continue
        return model
    return None


def same_dongle(device, models=None):
    """Known vid/pid but no model matches: another remote on the same scheme."""
    return (device.vendor, device.product) in supported_pairs(models) and match(device, models) is None
