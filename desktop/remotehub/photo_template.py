"""User photo and fixed key codes verified from the real receiver's reports."""
import base64
import json
from pathlib import Path
from .model import Action, Button, Profile

KEYMAP=json.loads((Path(__file__).parent/"assets/tv-keymap.json").read_text(encoding="utf-8"))


def is_fixed_model(profile):
    """The adapted model ships a verified key table; its keys are not learned."""
    return (profile.vendor,profile.product)==(KEYMAP["vendor"],KEYMAP["product"])


def apply_fixed_keys(profile):
    """Refresh fixed identities; the physical voice key always controls voice."""
    if (profile.vendor,profile.product)!=(KEYMAP["vendor"],KEYMAP["product"]):return False
    changed=False
    for button in profile.buttons:
        if button.id in KEYMAP["keys"] or button.id in KEYMAP["excluded"]:
            trigger=KEYMAP["keys"].get(button.id,{}).get("trigger","")
            if button.trigger!=trigger:button.trigger=trigger; changed=True
        if is_voice_button(profile, button):
            if button.action != Action("voice"):
                button.action = Action("voice")
                changed = True
            for name in ("double_action", "long_action"):
                if getattr(button, name).kind != "none":
                    setattr(button, name, Action())
                    changed = True
    return changed


def is_voice_button(profile, button):
    return bool(button and is_fixed_model(profile) and
                (button.id == "tv-voice" or button.trigger == KEYMAP["keys"]["tv-voice"]["trigger"]))

def television_profile():
    profile=Profile(id="tv-photo",name="USB 0416:0602")
    profile.image=base64.b64encode((Path(__file__).parent/"assets/remote-tv.png").read_bytes()).decode()
    # Geometry lives in remotehub/models/<id>.json so a second remote only
    # needs a data file, not code changes.
    from . import models
    model = models.by_pair(KEYMAP["vendor"], KEYMAP["product"])
    if model is None or not model.regions:
        raise RuntimeError("缺少这款遥控器的模型定义 remotehub/models/")
    regions = model.regions
    profile.buttons=[Button(id="tv-"+key,name=name,rect=[x/793,y/1983,w/793,h/1983]) for key,name,x,y,w,h in regions]
    apply_fixed_keys(profile)
    profile.validate()
    return profile
