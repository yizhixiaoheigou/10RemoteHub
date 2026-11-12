"""The model registry decides what an attached remote is; no user pick involved."""
from remotehub import models
from remotehub.inventory import USBDevice, receiver_state
from remotehub.photo_template import television_profile


def device(**kwargs):
    base = dict(vendor=0x0416, product=0x0602, serial='example_receiver_1', name='Receiver',
                connection='port', bcd_device=0x0100)
    base.update(kwargs)
    return USBDevice(**base)


def test_registry_ships_the_adapted_model():
    loaded = models.load()
    model = next(m for m in loaded if m.id == 'usb-0416-0602')
    assert model.pair == (0x0416, 0x0602)
    assert model.bcd_device == 0x0100
    assert len(model.regions) == 30
    assert model.keymap.endswith('tv-keymap.json')


def test_exact_device_matches_and_geometry_comes_from_the_model():
    assert models.match(device()) is not None
    profile = television_profile()
    assert len(profile.buttons) == 30
    assert profile.buttons[0].id == 'tv-power'


def test_other_firmware_is_reported_as_unadapted():
    other = device(bcd_device=0x0101)
    assert models.match(other) is None
    state = receiver_state(television_profile(), [other], checked=True)
    assert state.code == 'unadapted' and not state.usable
    assert 'bcd 0101' in state.detail


def test_missing_firmware_field_still_matches():
    assert models.match(device(bcd_device=None)) is not None


def test_serial_is_reported_but_never_rejects_a_unit():
    other = device(serial='OTHER_B_2')
    assert models.match(other) is not None
    assert 'serial OTHER' in models.fingerprint(other)


def test_unknown_vendor_is_unsupported():
    from remotehub.model import Profile
    unknown = Profile(vendor=0x1234, product=0x9999)
    state = receiver_state(unknown, [device(vendor=0x1234, product=0x9999)], checked=True)
    assert state.code == 'unsupported'
