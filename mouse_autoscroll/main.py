"""mouse-autoscroll: Windows-style middle-click autoscroll for any mouse."""

import argparse
import os
import selectors
import signal
import socket
import sys
import time
from pathlib import Path

from . import hyprland
from .config import load
from .engine import IDLE, Engine, Geometry, StateChange
from .publisher import StatePublisher

WATCHDOG_EVERY = 1.0  # seconds; the unit's WatchdogSec is several times this
# Retry mice we couldn't take. A full scan (~50 ms) runs only while we hold no
# mouse at all, so it can never stutter a pointer we are forwarding. Covers
# starting before logind has given us access to the mouse (login race).
RESCAN_EVERY = 5.0


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mouse-autoscroll" / "config.toml"


class Notifier:
    """systemd sd_notify without libsystemd: one datagram per message."""

    def __init__(self):
        addr = os.environ.get("NOTIFY_SOCKET")
        if addr and addr.startswith("@"):
            addr = "\0" + addr[1:]
        self._addr = addr
        self._last = 0.0

    def send(self, msg: str) -> None:
        if not self._addr:
            return
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
                s.sendto(msg.encode(), self._addr)
        except OSError:
            pass

    def watchdog(self, now: float) -> None:
        if now - self._last >= WATCHDOG_EVERY:
            self._last = now
            self.send("WATCHDOG=1")


def parse_args(argv):
    p = argparse.ArgumentParser(prog="mouse-autoscroll", description=__doc__)
    p.add_argument("--list", action="store_true",
                   help="show which input devices would get autoscroll, grab nothing")
    p.add_argument("--timeout", type=float, default=0,
                   help="exit by itself after this many seconds (for testing)")
    p.add_argument("--config", type=Path, default=config_path())
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--trace", action="store_true",
                   help="log every scroll tick: pointer, offset, wheel sent (debugging)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        from . import devices
    except ImportError as e:
        log(f"mouse-autoscroll: missing dependency ({e}); "
            "install python-evdev and python-pyudev")
        return 1

    ctx = devices.udev_context()
    if args.list:
        for dev in devices.input_nodes(ctx):
            mark = "YES" if devices.qualifies(dev) else " no"
            parent = dev.parent  # the inputN device carries the name
            name = (parent.properties.get("NAME", "?") if parent else "?").strip('"')
            log(f"{mark}  {dev.device_node}  {name}")
        return 0

    cfg, warnings = load(args.config)
    for w in warnings:
        log(f"config: {w}")

    hypr_sock = lambda: hyprland.find_socket(  # noqa: E731  (re-found each press)
        runtime_dir(), os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))
    publisher = StatePublisher(runtime_dir() / "mouse-autoscroll" / "state.sock")
    notifier = Notifier()
    sel = selectors.DefaultSelector()
    mice: dict[str, "devices.Mouse"] = {}

    def mode_for_press():
        cls = hyprland.active_window_class(hypr_sock())
        mode = cfg.rules.mode_for(cls)
        if args.verbose:
            log(f"press: window={cls!r} mode={mode}")
        return mode

    origins: dict[str, tuple[int, int]] = {}

    def geometry_for(node):
        def geometry_for_press():
            sock = hypr_sock()
            pos = hyprland.cursor_pos(sock)
            if pos is None:
                origins.pop(node, None)
                return None
            origins[node] = pos
            mon = hyprland.monitor_at(sock, *pos)
            if args.verbose:
                log(f"origin={pos} monitor={mon}")
            if mon is None:
                return None
            return Geometry(pos[0], pos[1], *mon)
        return geometry_for_press

    def make_engine(mouse):
        return Engine(cfg.curve, mode_for_press,
                      geometry_for_press=geometry_for(mouse.node),
                      free_pointer=cfg.free_pointer)

    failed: dict[str, object] = {}  # node -> udev device we couldn't take yet

    def add(udev_dev):
        node = udev_dev.device_node
        if node in mice or not devices.qualifies(udev_dev):
            return
        try:
            mouse = devices.Mouse(node, make_engine)
        except OSError as e:
            if node not in failed:
                log(f"cannot take {node}: {e} (will keep retrying)")
            failed[node] = udev_dev
            return
        failed.pop(node, None)
        mice[node] = mouse
        sel.register(mouse, selectors.EVENT_READ, "mouse")
        log(f"grabbed {node} ({mouse.name})")

    def remove(node):
        mouse = mice.pop(node, None)
        if mouse is None:
            return
        try:
            sel.unregister(mouse)
        except (KeyError, ValueError):
            pass
        if mouse.engine.state != IDLE:
            publisher.publish(IDLE, None)
        mouse.close()
        log(f"released {node}")

    def apply(mouse, outputs):
        for out in outputs:
            if isinstance(out, StateChange):
                publisher.publish(out.state, origins.get(mouse.node))
                if args.verbose:
                    log(f"state: {out.state}")
            else:
                mouse.write(*out)

    # Signals wake the select loop through a socketpair.
    wake_r, wake_w = socket.socketpair()
    wake_r.setblocking(False)
    wake_w.setblocking(False)
    signal.set_wakeup_fd(wake_w.fileno())
    stop = False

    def on_signal(signum, frame):
        nonlocal stop
        stop = True

    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, on_signal)

    hotplug = devices.Hotplug(ctx)
    sel.register(hotplug, selectors.EVENT_READ, "hotplug")
    sel.register(publisher, selectors.EVENT_READ, "publisher")
    sel.register(wake_r, selectors.EVENT_READ, "wake")

    for dev in devices.input_nodes(ctx):
        add(dev)
    if not mice:
        log("no mouse taken yet; retrying every 5 s and watching for new ones")

    notifier.send("READY=1")
    deadline = time.monotonic() + args.timeout if args.timeout > 0 else None
    tick_every = 1.0 / cfg.tick_hz
    last_scan = time.monotonic()

    try:
        while not stop:
            now = time.monotonic()
            if deadline and now >= deadline:
                log("timeout reached, exiting")
                break
            notifier.watchdog(now)
            if now - last_scan >= RESCAN_EVERY and not any(
                    m.engine.scrolling for m in mice.values()):
                last_scan = now
                for dev in (devices.input_nodes(ctx) if not mice else list(failed.values())):
                    add(dev)
            scrolling = any(m.engine.scrolling for m in mice.values())
            wait = tick_every if scrolling else WATCHDOG_EVERY
            if deadline:
                wait = max(0.0, min(wait, deadline - now))

            for key, _ in sel.select(timeout=wait):
                kind = key.data
                if kind == "mouse":
                    mouse = key.fileobj
                    if mouse.node not in mice:
                        continue
                    try:
                        events = mouse.read()
                    except OSError:
                        remove(mouse.node)
                        continue
                    for ev in events:
                        apply(mouse, mouse.engine.handle(
                            ev.type, ev.code, ev.value, now=time.monotonic()))
                elif kind == "hotplug":
                    for action, dev in hotplug.pending():
                        if action == "add":
                            devices.wait_for_node(dev)
                            add(dev)
                        elif action == "remove":
                            failed.pop(dev.device_node, None)
                            remove(dev.device_node)
                elif kind == "publisher":
                    publisher.accept()
                elif kind == "wake":
                    try:
                        wake_r.recv(64)
                    except BlockingIOError:
                        pass

            now = time.monotonic()
            pointer = None
            if any(m.engine.free for m in mice.values()):
                pointer = hyprland.cursor_pos(hypr_sock())  # one query per tick
            for mouse in list(mice.values()):
                if mouse.engine.scrolling:
                    outputs = mouse.engine.tick(now, pointer)
                    if args.trace:
                        v = sum(o[2] for o in outputs if isinstance(o, tuple) and o[1] == 0x0B)
                        h = sum(o[2] for o in outputs if isinstance(o, tuple) and o[1] == 0x0C)
                        ox, oy = mouse.engine.offset
                        log(f"tick {now:.3f} ptr={pointer} off=({ox:.0f},{oy:.0f}) "
                            f"hires_v={v} hires_h={h} events={len(outputs)}")
                    apply(mouse, outputs)
    finally:
        for node in list(mice):
            remove(node)
        publisher.close()
        notifier.send("STOPPING=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
