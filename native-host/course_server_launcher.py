#!/usr/bin/python3
"""Chrome native-messaging launcher for the on-demand course server."""
import json
import fcntl
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/Users/yzj/Projects/Courses Studyspace")
PYTHON = ROOT / ".venv-mlx/bin/python"
SERVER = ROOT / "local_server.py"
LOG = ROOT / "runtime/on-demand-server.log"
LOCK = ROOT / "runtime/course-server-launch.lock"
HOST = "127.0.0.1"
PORT = 4317


def receive():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) != 4:
        return None
    length = struct.unpack("=I", raw_length)[0]
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def send(payload):
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def listening():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.4):
            return True
    except OSError:
        return False


def start_server():
    if listening():
        return {"ok": True, "already_running": True}
    if not PYTHON.exists() or not SERVER.exists():
        return {"ok": False, "error": "课程服务文件不完整，请打开 Courses Studyspace 项目检查"}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("ab") as output:
        subprocess.Popen(
            [str(PYTHON), str(SERVER)], cwd=str(ROOT), stdout=output, stderr=output,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env={**os.environ, "COURSE_SERVER_IDLE_SECONDS": "120"},
        )
    for _ in range(40):
        if listening():
            return {"ok": True, "already_running": False}
        time.sleep(0.25)
    return {"ok": False, "error": "课程服务在 10 秒内没有启动，请查看 runtime/on-demand-server.log"}


message = receive()
if message is not None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        result = start_server() if message.get("action") == "start" else {"ok": False, "error": "未知操作"}
    send(result)
