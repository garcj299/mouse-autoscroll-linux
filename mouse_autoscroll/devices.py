"""Physical mice: discovery, hotplug, grab, and the uinput clone.
The only module that touches evdev/uinput/udev."""

import time

import evdev
import pyudev

from .engine import (
    BTN_TASK,
    EV_KEY,
    EV_MSC,
    EV_REL,
    REL_HWHEEL,
    REL_HWHEEL_HI_RES,
    REL_WHEEL,
    REL_WHEEL_HI_RES,
    Engine,
)
from .selection import is_autoscroll_mouse

CLONE_SUFFIX = " (autoscroll)"
_KEEP_TYPES = (EV_KEY, EV_REL, EV_MSC)
_WHEELS = [REL_WHEEL, REL_HWHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES]


def udev_context() -> pyudev.Context:
    return pyudev.Context()


def input_nodes(ctx: pyudev.Context):
    for dev in ctx.list_devices(subsystem="input"):
        if dev.device_node and dev.sys_name.startswith("event"):
            yield dev


def qualifies(udev_dev) -> bool:
    """Check a udev input node without grabbing it."""
    try:
        d = evdev.InputDevice(udev_dev.device_node)
    except OSError:
        return False
    try:
        caps = d.capabilities(absinfo=False)
    except OSError:
        return False
    finally:
        d.close()
    return is_autoscroll_mouse(dict(udev_dev.properties), udev_dev.sys_path, caps)


class Mouse:
    """One grabbed physical mouse, its clone, and its engine."""

    def __init__(self, node: str, engine_factory):
        self.node = node
        self.dev = evdev.InputDevice(node)
        # Grab first: if it fails (another program holds it, no access yet),
        # no clone is created, so retries don't flash virtual devices.
        try:
            self.dev.grab()
        except OSError:
            self.dev.close()
            raise
        try:
            caps = self.dev.capabilities(absinfo=False)
            events = {t: list(caps.get(t, [])) for t in _KEEP_TYPES if caps.get(t)}
            rel = events.setdefault(EV_REL, [])
            rel += [c for c in _WHEELS if c not in rel]
            keys = events.setdefault(EV_KEY, [])
            if BTN_TASK not in keys:
                keys.append(BTN_TASK)  # held while scrolling with a free pointer
            info = self.dev.info
            self.ui = evdev.UInput(
                events=events,
                name=(self.dev.name + CLONE_SUFFIX)[:79],
                vendor=info.vendor,
                product=info.product,
                version=info.version,
                bustype=info.bustype,
                phys="mouse-autoscroll",
            )
        except Exception:
            self.dev.ungrab()
            self.dev.close()
            raise
        self.name = self.dev.name
        self.engine: Engine = engine_factory(self)

    def fileno(self) -> int:
        return self.dev.fd

    def read(self):
        """Pending events, or raises OSError if the device is gone."""
        try:
            return list(self.dev.read())
        except BlockingIOError:
            return []

    def write(self, ev_type: int, code: int, value: int) -> None:
        self.ui.write(ev_type, code, value)

    def close(self) -> None:
        for ev in self.engine.shutdown():
            try:
                self.write(*ev)
            except OSError:
                pass
        for action in (self.dev.ungrab, self.ui.close, self.dev.close):
            try:
                action()
            except OSError:
                pass


class Hotplug:
    """udev add/remove events for input nodes, readable via select."""

    def __init__(self, ctx: pyudev.Context):
        self._monitor = pyudev.Monitor.from_netlink(ctx)
        self._monitor.filter_by("input")
        self._monitor.start()

    def fileno(self) -> int:
        return self._monitor.fileno()

    def pending(self):
        while True:
            dev = self._monitor.poll(timeout=0)
            if dev is None:
                return
            if dev.sys_name.startswith("event") and dev.device_node:
                yield dev.action, dev


def wait_for_node(udev_dev, attempts: int = 10) -> None:
    """A freshly added node can need a moment before its ACL is applied."""
    for _ in range(attempts):
        try:
            with open(udev_dev.device_node, "rb"):
                return
        except PermissionError:
            time.sleep(0.05)
        except OSError:
            return

