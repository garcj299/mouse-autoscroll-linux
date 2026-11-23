import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from mouse_autoscroll import hyprland


def make_instance(root: Path, name: str, mtime: float) -> Path:
    d = root / "hypr" / name
    d.mkdir(parents=True)
    sock = d / ".socket.sock"
    sock.touch()
    os.utime(d, (mtime, mtime))
    return sock


class FindSocketTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_none_when_no_hyprland(self):
        self.assertIsNone(hyprland.find_socket(self.root, None))

    def test_signature_from_env_wins(self):
        a = make_instance(self.root, "aaa", 100)
        make_instance(self.root, "bbb", 200)
        self.assertEqual(hyprland.find_socket(self.root, "aaa"), a)

    def test_newest_instance_without_env(self):
        make_instance(self.root, "aaa", 100)
        b = make_instance(self.root, "bbb", 200)
        self.assertEqual(hyprland.find_socket(self.root, None), b)

    def test_stale_env_signature_falls_back(self):
        b = make_instance(self.root, "bbb", 200)
        self.assertEqual(hyprland.find_socket(self.root, "gone"), b)


class FakeHyprland:
    """A one-shot UNIX socket server answering like Hyprland's IPC."""

    def __init__(self, reply: bytes, delay: float = 0.0):
        self.path = Path(tempfile.mkdtemp()) / ".socket.sock"
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(self.path))
        self.server.listen(1)
        self.received = None
        threading.Thread(target=self._serve, args=(reply, delay), daemon=True).start()

    def _serve(self, reply, delay):
        conn, _ = self.server.accept()
        self.received = conn.recv(1024)
        time.sleep(delay)
        try:
            conn.sendall(reply)
        except OSError:
            pass
        conn.close()


class QueryTest(unittest.TestCase):
    def test_active_window_class(self):
        fake = FakeHyprland(b'{"address": "0x1", "class": "kitty", "title": "x"}')
        self.assertEqual(hyprland.active_window_class(fake.path), "kitty")
        self.assertEqual(fake.received, b"j/activewindow")

    def test_no_active_window(self):
        fake = FakeHyprland(b"{}")
        self.assertIsNone(hyprland.active_window_class(fake.path))

    def test_cursor_pos(self):
        fake = FakeHyprland(b'\n{\n    "x": 4397,\n    "y": 785\n}\n')
        self.assertEqual(hyprland.cursor_pos(fake.path), (4397, 785))

    # Real layout on cyriaendureo, 2026-11-23 (sizes are physical pixels)
    MONITORS = (
        b'[{"name": "eDP-1", "x": 0, "y": 1120, "width": 1920, "height": 1200,'
        b' "scale": 1.5, "transform": 0},'
        b' {"name": "DP-5", "x": 1280, "y": 0, "width": 1920, "height": 1080,'
        b' "scale": 1.0, "transform": 0}]'
    )

    def test_monitor_at_uses_logical_size(self):
        fake = FakeHyprland(self.MONITORS)
        self.assertEqual(hyprland.monitor_at(fake.path, 500, 1500), (0, 1120, 1280, 800))
        self.assertEqual(fake.received, b"j/monitors")

    def test_monitor_at_second_monitor(self):
        fake = FakeHyprland(self.MONITORS)
        self.assertEqual(hyprland.monitor_at(fake.path, 2000, 500), (1280, 0, 1920, 1080))

    def test_rotated_monitor_swaps_size(self):
        fake = FakeHyprland(
            b'[{"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 1, "transform": 1}]'
        )
        self.assertEqual(hyprland.monitor_at(fake.path, 10, 1500), (0, 0, 1080, 1920))

    def test_point_outside_all_monitors(self):
        fake = FakeHyprland(self.MONITORS)
        self.assertIsNone(hyprland.monitor_at(fake.path, 10, 10))

    def test_garbage_reply_is_none(self):
        fake = FakeHyprland(b"not json")
        self.assertIsNone(hyprland.active_window_class(fake.path))

    def test_no_socket_is_none(self):
        self.assertIsNone(hyprland.active_window_class(None))
        self.assertIsNone(hyprland.active_window_class(Path("/nonexistent.sock")))

    def test_slow_reply_times_out(self):
        fake = FakeHyprland(b'{"class": "kitty"}', delay=0.5)
        t = time.monotonic()
        self.assertIsNone(hyprland.active_window_class(fake.path, timeout=0.1))
        self.assertLess(time.monotonic() - t, 0.3)


if __name__ == "__main__":
    unittest.main()
