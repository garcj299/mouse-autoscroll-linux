"""Which input devices get autoscroll. Decided by what the device is and
can do (udev properties + evdev capabilities), never by name or VID/PID,
so any future mouse qualifies on its own."""

from .engine import BTN_MIDDLE, EV_KEY, EV_REL, REL_X, REL_Y

EV_ABS = 0x03
_EXCLUDING_FLAGS = (
    "ID_INPUT_POINTINGSTICK",  # trackpoint keeps libinput's own middle-button scroll
    "ID_INPUT_TOUCHPAD",
    "ID_INPUT_TABLET",
    "ID_INPUT_TOUCHSCREEN",
    "ID_INPUT_JOYSTICK",
)


def is_autoscroll_mouse(props: dict, sys_path: str, caps: dict) -> bool:
    if props.get("ID_INPUT_MOUSE") != "1":
        return False
    if any(props.get(flag) == "1" for flag in _EXCLUDING_FLAGS):
        return False
    # Our own clones and every other uinput device live here; skipping them
    # means we can never grab ourselves into a loop.
    if "/devices/virtual/" in sys_path:
        return False
    if caps.get(EV_ABS):
        return False
    rel = set(caps.get(EV_REL, []))
    return BTN_MIDDLE in caps.get(EV_KEY, []) and {REL_X, REL_Y} <= rel
