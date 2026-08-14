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


def build_server_environment(inherited=None):
    child_env = dict(os.environ if inherited is None else inherited)
    home = Path(child_env.get("HOME") or Path.home())
    child_env["PATH"] = os.pathsep.join([
        str(home / ".npm-global" / "bin"),
        "/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ])
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        child_env.pop(key, None)
    child_env["COURSE_SERVER_IDLE_SECONDS"] = "120"
    return child_env


def start_server():
    if listening():
        return {"ok": True, "already_running": True}
    if not PYTHON.exists() or not SERVER.exists():
        return {"ok": False, "error": "课程服务文件不完整，请打开 Courses Studyspace 项目检查"}
    # Chrome can retain proxy variables from an earlier login session.  A dead
    # localhost proxy makes every course-media request fail with ECONNREFUSED.
    child_env = build_server_environment()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("ab") as output:
        subprocess.Popen(
            [str(PYTHON), str(SERVER)], cwd=str(ROOT), stdout=output, stderr=output,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env=child_env,
        )
    for _ in range(40):
        if listening():
            return {"ok": True, "already_running": False}
        time.sleep(0.25)
    return {"ok": False, "error": "课程服务在 10 秒内没有启动，请查看 runtime/on-demand-server.log"}


def click_player(message):
    try:
        x = round(float(message.get("x")))
        y = round(float(message.get("y")))
    except (TypeError, ValueError):
        return {"ok": False, "error": "播放器按钮坐标无效"}
    if not (0 <= x <= 10000 and 0 <= y <= 10000):
        return {"ok": False, "error": "播放器按钮坐标超出屏幕"}
    script = f'tell application "System Events" to click at {{{x}, {y}}}'
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script], capture_output=True, text=True, timeout=3,
    )
    if result.returncode:
        return {"ok": False, "error": result.stderr.strip() or "无法点击课程播放器"}
    return {"ok": True}


def main():
    message = receive()
    if message is None:
        return
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        action = message.get("action")
        if action == "start":
            result = start_server()
        elif action == "click_player":
            result = click_player(message)
        else:
            result = {"ok": False, "error": "未知操作"}
    send(result)


if __name__ == "__main__":
    main()
