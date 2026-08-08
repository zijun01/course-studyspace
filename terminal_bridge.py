#!/usr/bin/env python3
"""Local PTY sessions that expose the native Codex terminal UI to the extension."""
from __future__ import annotations

import base64
import fcntl
import os
import pty
import shutil
import struct
import subprocess
import termios
import threading
import time
import uuid
from collections import deque
from pathlib import Path


class TerminalSession:
    def __init__(self, cwd: Path, cols: int = 80, rows: int = 24):
        self.id = uuid.uuid4().hex
        self.cwd = cwd
        self.created_at = time.time()
        self.updated_at = self.created_at
        self._chunks: deque[tuple[int, bytes]] = deque(maxlen=4000)
        self._sequence = 0
        self._lock = threading.Lock()
        master, slave = pty.openpty()
        self.master = master
        self.resize(cols, rows)
        environment = dict(os.environ)
        environment.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "CLICOLOR": "1"})
        codex = shutil.which("codex") or str(Path.home() / ".npm-global/bin/codex")
        self.process = subprocess.Popen(
            [codex, "-C", str(cwd)],
            cwd=cwd,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=environment,
            start_new_session=True,
            close_fds=True,
        )
        os.close(slave)
        threading.Thread(target=self._read_loop, daemon=True, name=f"course-terminal-{self.id[:8]}").start()

    def _read_loop(self):
        try:
            while True:
                data = os.read(self.master, 65536)
                if not data:
                    break
                with self._lock:
                    self._sequence += 1
                    self._chunks.append((self._sequence, data))
                    self.updated_at = time.time()
        except OSError:
            pass

    def output(self, since: int) -> dict:
        with self._lock:
            chunks = [data for sequence, data in self._chunks if sequence > since]
            cursor = self._sequence
        return {
            "data": base64.b64encode(b"".join(chunks)).decode("ascii"),
            "cursor": cursor,
            "alive": self.process.poll() is None,
            "exit_code": self.process.poll(),
        }

    def write(self, data: str):
        if self.process.poll() is not None:
            raise RuntimeError("Codex 终端已经退出")
        os.write(self.master, data.encode("utf-8"))
        self.updated_at = time.time()

    def resize(self, cols: int, rows: int):
        cols = max(20, min(int(cols), 400))
        rows = max(6, min(int(rows), 200))
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            os.close(self.master)
        except OSError:
            pass


class TerminalBridge:
    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}
        self._course_sessions: dict[str, str] = {}
        self._lock = threading.Lock()

    def start(self, course_key: str, cwd: Path, cols: int = 80, rows: int = 24, force: bool = False) -> TerminalSession:
        cwd = cwd.resolve()
        if not cwd.is_dir():
            raise ValueError("当前课程资料目录还不存在")
        with self._lock:
            existing_id = self._course_sessions.get(course_key)
            existing = self._sessions.get(existing_id or "")
            if existing and not force and existing.process.poll() is None and existing.cwd == cwd:
                existing.resize(cols, rows)
                return existing
            if existing:
                existing.close()
            session = TerminalSession(cwd, cols, rows)
            self._sessions[session.id] = session
            self._course_sessions[course_key] = session.id
            return session

    def get(self, session_id: str) -> TerminalSession:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError("终端会话不存在")
        return session

    def stop(self):
        for session in list(self._sessions.values()):
            session.close()


bridge = TerminalBridge()
