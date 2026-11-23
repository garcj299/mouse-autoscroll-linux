"""Autoscroll state machine for one mouse.

Pure logic, no devices: evdev events go in through ``handle`` and ``tick``.
What comes out is a list mixing:

* ``(type, code, value)`` tuples to write to the mouse's virtual clone;
* ``StateChange`` objects, for the indicator.
"""

from dataclasses import dataclass
from typing import Callable

from .curve import Curve, speed
from .modes import FULL, HOLD, IGNORE

# evdev constants (linux/input-event-codes.h), kept here so the logic
# can be tested without python-evdev installed.
EV_SYN, EV_KEY, EV_REL, EV_MSC = 0x00, 0x01, 0x02, 0x04
SYN_REPORT = 0
MSC_SCAN = 0x04
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
# Held on the clone while scrolling with a free pointer: while any button is
# down, the compositor keeps pointer focus (and so the wheel) on the window
# where it was pressed. Almost no app gives this button a meaning.
BTN_TASK = 0x117
BTN_MOUSE_FIRST, BTN_MOUSE_LAST = 0x110, 0x11F
REL_X, REL_Y = 0x00, 0x01
REL_HWHEEL, REL_WHEEL = 0x06, 0x08
REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES = 0x0B, 0x0C
WHEEL_CODES = {REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES}

HIRES_PER_NOTCH = 120  # kernel convention for REL_*_HI_RES
MAX_OFFSET = 3000  # px; clamp when the screen geometry is unknown
FROZEN_GAIN = 0.6  # mouse units -> px when the pointer is frozen (no real position)
MAX_TICK_DT = 0.1  # a stalled loop must not turn into one huge jump

# Public states (what the indicator sees)
IDLE = "idle"
SCROLLING = "scrolling"  # middle button held
LATCHED = "latched"  # clicked once; scrolls until the next click
_PENDING = "pending"  # hold mode: pressed, not yet moved past the dead zone

SYN = (EV_SYN, SYN_REPORT, 0)


@dataclass(frozen=True)
class StateChange:
    state: str


@dataclass(frozen=True)
class Geometry:
    """Where autoscroll started and the monitor it started on (logical px)."""

    origin_x: int
    origin_y: int
    x: int
    y: int
    width: int
    height: int

    def limits(self, axis: str) -> tuple[float, float, float]:
        """(max px towards negative, max px towards positive, screen size)."""
        if axis == "x":
            o, start, size = self.origin_x, self.x, self.width
        else:
            o, start, size = self.origin_y, self.y, self.height
        return max(o - start, 0), max(start + size - 1 - o, 0), size


def _is_button(code: int) -> bool:
    return BTN_MOUSE_FIRST <= code <= BTN_MOUSE_LAST


class Engine:
    def __init__(
        self,
        curve: Curve,
        mode_for_press: Callable[[], str],
        gain: float = FROZEN_GAIN,
        geometry_for_press: Callable[[], Geometry | None] = lambda: None,
        free_pointer: bool = True,
    ):
        self._curve = curve
        self._mode_for_press = mode_for_press
        self._gain = gain  # mouse units -> px, for the click/hold split and frozen mode
        self._geometry_for_press = geometry_for_press
        self._free_pointer = free_pointer
        self._free = False  # this scroll: real pointer moves, speed from its position
        self._origin = (0, 0)
        self._ux = self._uy = 0.0  # mouse movement since the press, in px
        self._limits = {"x": (MAX_OFFSET, MAX_OFFSET, None), "y": (MAX_OFFSET, MAX_OFFSET, None)}
        self._state = IDLE
        self._latch_on_release = False
        self._moved = False
        self._ox = self._oy = 0.0  # virtual offset from the origin
        self._acc_v = self._acc_h = 0.0  # fractional hi-res units
        self._notch_v = self._notch_h = 0  # hi-res units not yet a notch
        self._last_tick = 0.0
        self._consumed: set[int] = set()  # buttons whose release we eat
        self._clone_held: set[int] = set()  # buttons down on the clone
        self._eat_wheel_frame = False

    # -- public -----------------------------------------------------------

    @property
    def state(self) -> str:
        return IDLE if self._state == _PENDING else self._state

    @property
    def scrolling(self) -> bool:
        return self._state in (SCROLLING, LATCHED)

    def handle(self, ev_type: int, code: int, value: int, now: float) -> list:
        if ev_type == EV_KEY and _is_button(code):
            return self._button(code, value, now)
        if ev_type == EV_REL:
            return self._rel(code, value, now)
        if ev_type == EV_SYN:
            self._eat_wheel_frame = False
        return self._forward(ev_type, code, value)

    @property
    def offset(self) -> tuple[float, float]:
        """Current distance from the origin in px (x, y), for tracing."""
        return self._ox, self._oy

    @property
    def free(self) -> bool:
        """True while scrolling with a free pointer: tick() wants its position."""
        return self.scrolling and self._free

    def tick(self, now: float, pointer: tuple[int, int] | None = None) -> list:
        if not self.scrolling:
            return []
        if self._free and pointer is not None:
            self._ox = self._clamp("x", pointer[0] - self._origin[0])
            self._oy = self._clamp("y", pointer[1] - self._origin[1])
        dt = min(now - self._last_tick, MAX_TICK_DT)
        self._last_tick = now
        if dt <= 0:
            return []
        # Mouse down -> content down -> negative wheel. Right -> positive hwheel.
        self._acc_v += -self._axis_speed("y", self._oy) * dt * HIRES_PER_NOTCH
        self._acc_h += self._axis_speed("x", self._ox) * dt * HIRES_PER_NOTCH
        out = []
        out += self._wheel_axis("v", REL_WHEEL_HI_RES, REL_WHEEL)
        out += self._wheel_axis("h", REL_HWHEEL_HI_RES, REL_HWHEEL)
        if out:
            out.append(SYN)
        return out

    def shutdown(self) -> list:
        """Events that release every button still down on the clone."""
        out = [(EV_KEY, c, 0) for c in sorted(self._clone_held)]
        self._clone_held.clear()
        return out + [SYN] if out else []

    # -- internals --------------------------------------------------------

    def _forward(self, ev_type: int, code: int, value: int) -> list:
        if ev_type == EV_KEY:
            if value == 1:
                self._clone_held.add(code)
            elif value == 0:
                self._clone_held.discard(code)
        return [(ev_type, code, value)]

    def _set(self, state: str) -> list:
        public_before = self.state
        self._state = state
        out = [StateChange(self.state)] if self.state != public_before else []
        if self._free:
            holding = BTN_TASK in self._clone_held
            if self.scrolling and not holding:
                out += self._forward(EV_KEY, BTN_TASK, 1) + [SYN]
            elif not self.scrolling and holding:
                out += self._forward(EV_KEY, BTN_TASK, 0) + [SYN]
        return out

    def _start(self, state: str, latch_on_release: bool, now: float) -> list:
        geometry = self._geometry_for_press()
        self._free = self._free_pointer and geometry is not None
        if geometry is not None:
            self._origin = (geometry.origin_x, geometry.origin_y)
        for axis in ("x", "y"):
            self._limits[axis] = (
                geometry.limits(axis) if geometry else (MAX_OFFSET, MAX_OFFSET, None)
            )
        self._latch_on_release = latch_on_release
        self._moved = False
        self._ox = self._oy = 0.0
        self._ux = self._uy = 0.0
        self._acc_v = self._acc_h = 0.0
        self._notch_v = self._notch_h = 0
        self._last_tick = now
        return self._set(state)

    def _button(self, code: int, value: int, now: float) -> list:
        if value == 0:
            if code in self._consumed:
                self._consumed.discard(code)
                return []
            if code == BTN_MIDDLE and self._state == _PENDING:
                self._set(IDLE)
                return self._replay_middle_click()
            if code == BTN_MIDDLE and self._state == SCROLLING:
                if self._latch_on_release and not self._moved:
                    return self._set(LATCHED)
                return self._set(IDLE)
            return self._forward(EV_KEY, code, value)

        if value == 2:  # autorepeat
            if self._state == IDLE and code not in self._consumed:
                return self._forward(EV_KEY, code, value)
            return []

        # press
        if self._state == IDLE:
            if code != BTN_MIDDLE:
                return self._forward(EV_KEY, code, value)
            mode = self._mode_for_press()
            if mode == IGNORE:
                return self._forward(EV_KEY, code, value)
            if mode == HOLD:
                return self._start(_PENDING, latch_on_release=False, now=now)
            return self._start(SCROLLING, latch_on_release=True, now=now)

        self._consumed.add(code)
        if self._state == LATCHED:
            return self._set(IDLE)
        return []  # held scroll or pending: swallow, keep going

    def _rel(self, code: int, value: int, now: float) -> list:
        if self._state == IDLE:
            if self._eat_wheel_frame and code in WHEEL_CODES:
                return []
            return self._forward(EV_REL, code, value)

        if code in WHEEL_CODES:
            if self._state == LATCHED:
                self._eat_wheel_frame = True
                return self._set(IDLE)
            return []

        if code not in (REL_X, REL_Y):
            return []
        if code == REL_X:
            self._ux += value * self._gain
            if not self._free:
                self._ox = self._clamp("x", self._ux)
        else:
            self._uy += value * self._gain
            if not self._free:
                self._oy = self._clamp("y", self._uy)
        # Free pointer: the motion reaches the screen; frozen: it only feeds the offset.
        out = [(EV_REL, code, value)] if self._free else []
        if max(abs(self._ux), abs(self._uy)) > self._curve.deadzone:
            self._moved = True
            if self._state == _PENDING:
                self._last_tick = now
                out += self._set(SCROLLING)
        return out

    def _clamp(self, axis: str, offset: float) -> float:
        neg, pos, _ = self._limits[axis]
        return max(-neg, min(pos, offset))

    def _axis_speed(self, axis: str, offset: float) -> float:
        neg, pos, size = self._limits[axis]
        if size is None:
            return speed(offset, self._curve)
        return speed(offset, self._curve, pos if offset > 0 else neg, size)

    def _replay_middle_click(self) -> list:
        return [(EV_KEY, BTN_MIDDLE, 1), SYN, (EV_KEY, BTN_MIDDLE, 0), SYN]

    def _wheel_axis(self, axis: str, hires_code: int, notch_code: int) -> list:
        acc_name, notch_name = f"_acc_{axis}", f"_notch_{axis}"
        acc = getattr(self, acc_name)
        emit = int(acc)  # truncates toward zero; the remainder carries over
        setattr(self, acc_name, acc - emit)
        if not emit:
            return []
        notch_acc = getattr(self, notch_name) + emit
        notches = int(notch_acc / HIRES_PER_NOTCH)
        setattr(self, notch_name, notch_acc - notches * HIRES_PER_NOTCH)
        out = [(EV_REL, hires_code, emit)]
        if notches:
            out.append((EV_REL, notch_code, notches))
        return out
