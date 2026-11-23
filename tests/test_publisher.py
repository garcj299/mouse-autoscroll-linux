import json
import socket
import tempfile
import unittest
from pathlib import Path

from mouse_autoscroll.publisher import StatePublisher


def connect(test, path):
    c = socket.socket(socket.AF_UNIX)
    test.addCleanup(c.close)
    c.settimeout(1)
    c.connect(str(path))
    return c


def read_line(c):
    buf = b""
    while not buf.endswith(b"\n"):
        buf += c.recv(1024)
    return json.loads(buf)


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "sub" / "state.sock"
        self.pub = StatePublisher(self.path)

    def tearDown(self):
        self.pub.close()

    def test_new_client_gets_current_state(self):
        c = connect(self, self.path)
        self.pub.accept()
        self.assertEqual(read_line(c), {"state": "idle", "x": None, "y": None})

    def test_publish_reaches_clients(self):
        c = connect(self, self.path)
        self.pub.accept()
        read_line(c)
        self.pub.publish("latched", (100, 200))
        self.assertEqual(read_line(c), {"state": "latched", "x": 100, "y": 200})

    def test_dead_client_is_dropped(self):
        c = connect(self, self.path)
        self.pub.accept()
        c.close()
        self.pub.publish("scrolling", None)  # must not raise
        self.pub.publish("idle", None)
        self.assertEqual(self.pub.client_count, 0)

    def test_stale_socket_file_replaced(self):
        self.pub.close()
        self.assertFalse(self.path.exists())
        self.path.touch()
        self.pub = StatePublisher(self.path)
        c = connect(self, self.path)
        self.pub.accept()
        self.assertEqual(read_line(c)["state"], "idle")

    def test_publish_without_clients(self):
        self.pub.publish("scrolling", (1, 2))  # nothing to do, no error


if __name__ == "__main__":
    unittest.main()
