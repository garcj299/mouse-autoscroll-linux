"""Publishes the autoscroll state as JSON lines on a UNIX socket, for the
indicator. Never blocks: a client that can't take a line at once is dropped."""

import json
import os
import socket
from pathlib import Path


class StatePublisher:
    def __init__(self, path: Path):
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.unlink()  # stale socket from a previous run
        except FileNotFoundError:
            pass
        self._server = socket.socket(socket.AF_UNIX)
        self._server.bind(str(path))
        os.chmod(path, 0o600)
        self._server.listen(4)
        self._server.setblocking(False)
        self._clients: list[socket.socket] = []
        self._last = self._line("idle", None)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def fileno(self) -> int:
        return self._server.fileno()

    def accept(self) -> None:
        try:
            conn, _ = self._server.accept()
        except BlockingIOError:
            return
        conn.setblocking(False)
        self._clients.append(conn)
        self._send(conn, self._last)

    def publish(self, state: str, pos: tuple[int, int] | None) -> None:
        self._last = self._line(state, pos)
        for conn in list(self._clients):
            self._send(conn, self._last)

    def close(self) -> None:
        for conn in self._clients:
            conn.close()
        self._clients.clear()
        self._server.close()
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _line(state: str, pos: tuple[int, int] | None) -> bytes:
        x, y = pos if pos else (None, None)
        return (json.dumps({"state": state, "x": x, "y": y}) + "\n").encode()

    def _send(self, conn: socket.socket, line: bytes) -> None:
        try:
            if conn.send(line) == len(line):
                return
        except OSError:
            pass
        conn.close()
        self._clients.remove(conn)
