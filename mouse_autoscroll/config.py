"""Config file loading. A broken file never stops the daemon: bad values
fall back to the defaults and come back as warnings."""

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from .curve import Curve
from .modes import ModeRules


@dataclass(frozen=True)
class Config:
    curve: Curve
    free_pointer: bool  # pointer moves while scrolling (like Zen); false = frozen
    tick_hz: float
    rules: ModeRules


DEFAULTS = Config(
    curve=Curve(
        deadzone=12, min_speed=1.0, slope=0.0086, exponent=1.3, edge_zone=0.05, max_speed=250
    ),
    free_pointer=True,
    tick_hz=120,
    rules=ModeRules(
        # Browsers have native autoscroll with link detection
        # (general.autoScroll = true); games use middle click as a control.
        ignore=["zen", "firefox", "steam_app_*"],
        # Middle click does something useful here: paste, open in a new tab,
        # open links, close tabs. Short click stays native, hold scrolls.
        hold=["kitty", "thunar", "code", "*obsidian*", "discord"],
    ),
)

# key in [scroll] -> (where it goes, minimum, minimum allowed?, exclusive maximum)
_SCROLL_KEYS = {
    "deadzone": ("curve", 0, True, None),
    "min_speed": ("curve", 0, False, None),
    "slope": ("curve", 0, True, None),
    "exponent": ("curve", 0, False, None),
    "edge_zone": ("curve", 0, True, 0.5),
    "max_speed": ("curve", 0, False, None),
    "sensitivity": ("curve", 0, False, None),
    "tick_hz": ("config", 0, False, None),
}


def load(path: Path) -> tuple[Config, list[str]]:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return DEFAULTS, []
    except (OSError, tomllib.TOMLDecodeError) as e:
        return DEFAULTS, [f"{path}: {e}; using defaults"]

    warnings: list[str] = []
    curve, rules = DEFAULTS.curve, DEFAULTS.rules
    top = {"free_pointer": DEFAULTS.free_pointer, "tick_hz": DEFAULTS.tick_hz}

    scroll = data.get("scroll", {})
    for key, value in scroll.items() if isinstance(scroll, dict) else []:
        if key == "free_pointer":
            if isinstance(value, bool):
                top[key] = value
            else:
                warnings.append(f"[scroll] {key} = {value!r}: must be true/false, using default")
            continue
        if key not in _SCROLL_KEYS:
            warnings.append(f"[scroll] {key}: unknown key, ignored")
            continue
        where, minimum, min_ok, maximum = _SCROLL_KEYS[key]
        ok_type = isinstance(value, (int, float)) and not isinstance(value, bool)
        ok_range = (
            ok_type
            and (value >= minimum if min_ok else value > minimum)
            and (maximum is None or value < maximum)
        )
        if not ok_range:
            warnings.append(f"[scroll] {key} = {value!r}: invalid, using default")
            continue
        if where == "config":
            top[key] = value
        else:
            curve = replace(curve, **{key: value})

    apps = data.get("apps", {})
    for key, value in apps.items() if isinstance(apps, dict) else []:
        if key not in ("ignore", "hold"):
            warnings.append(f"[apps] {key}: unknown key, ignored")
            continue
        if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            warnings.append(f"[apps] {key}: must be a list of strings, using default")
            continue
        rules = replace(rules, **{key: value})

    config = Config(
        curve=curve, free_pointer=top["free_pointer"], tick_hz=top["tick_hz"], rules=rules
    )
    return config, warnings
