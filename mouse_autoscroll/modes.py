"""Which autoscroll mode applies to a window, by its Hyprland class."""

from dataclasses import dataclass, field
from fnmatch import fnmatchcase

FULL = "full"  # Windows behaviour: click latches, hold scrolls while held
HOLD = "hold"  # short click stays a normal middle click; hold + move scrolls
IGNORE = "ignore"  # untouched


@dataclass(frozen=True)
class ModeRules:
    ignore: list[str] = field(default_factory=list)
    hold: list[str] = field(default_factory=list)

    def mode_for(self, window_class: str | None) -> str:
        """Unknown or missing class means FULL, so scrolling keeps working."""
        if not window_class:
            return FULL
        name = window_class.lower()
        if any(fnmatchcase(name, p.lower()) for p in self.ignore):
            return IGNORE
        if any(fnmatchcase(name, p.lower()) for p in self.hold):
            return HOLD
        return FULL
