"""Minimal, optional Hyprland IPC: the active window's class, the cursor
position and the monitor under it. Every failure returns None; the caller
carries on."""

import json
import socket
import time
from pathlib import Path

DEFAULT_TIMEOUT = 0.1  # seconds; past this a press is treated as "unknown window"


def find_socket(runtime_dir: Path, signature: str | None) -> Path | None:
    """The instance named by $HYPRLAND_INSTANCE_SIGNATURE if it exists,
    else the most recently started one. The service may not have the
    variable, and it goes stale when Hyprland restarts."""
    base = runtime_dir / "hypr"
    if signature:
        candidate = base / signature / ".socket.sock"
        if candidate.exists():
            return candidate
    try:
        instances = [d for d in base.iterdir() if (d / ".socket.sock").exists()]
    except OSError:
        return None
    if not instances:
        return None
    newest = max(instances, key=lambda d: d.stat().st_mtime)
    return newest / ".socket.sock"


def _request(path: Path | None, command: bytes, timeout: float):
    if path is None:
        return None
    deadline = time.monotonic() + timeout
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(command)
            chunks = []
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                s.settimeout(remaining)
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        return json.loads(b"".join(chunks))
    except (OSError, ValueError):
        return None


def active_window_class(path: Path | None, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    data = _request(path, b"j/activewindow", timeout)
    cls = data.get("class") if isinstance(data, dict) else None
    return cls if isinstance(cls, str) and cls else None


def cursor_pos(path: Path | None, timeout: float = DEFAULT_TIMEOUT) -> tuple[int, int] | None:
    data = _request(path, b"j/cursorpos", timeout)
    try:
        return int(data["x"]), int(data["y"])
    except (TypeError, KeyError, ValueError):
        return None


def monitor_at(
    path: Path | None, x: int, y: int, timeout: float = DEFAULT_TIMEOUT
) -> tuple[int, int, int, int] | None:
    """(x, y, width, height) in logical px of the monitor containing (x, y)."""
    data = _request(path, b"j/monitors", timeout)
    if not isinstance(data, list):
        return None
    for m in data:
        try:
            mx, my, scale = int(m["x"]), int(m["y"]), float(m["scale"]) or 1.0
            w, h = round(m["width"] / scale), round(m["height"] / scale)
            if int(m.get("transform", 0)) % 2 == 1:  # rotated 90/270
                w, h = h, w
        except (TypeError, KeyError, ValueError):
            continue
        if mx <= x < mx + w and my <= y < my + h:
            return mx, my, w, h
    return None
