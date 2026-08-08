#!/usr/bin/env python3
"""Small JSON-RPC bridge to the locally installed Codex app-server."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from collections import defaultdict, deque
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "library"
THREADS_FILE = LIBRARY / ".codex_threads.json"


class CodexBridge:
    def __init__(self):
        self.process = None
        self._next_id = 1
        self._write_lock = threading.Lock()
        self._pending = {}
        self._events = defaultdict(lambda: deque(maxlen=2000))
        self._approval_requests = {}
        self._threads = self._load_threads()
        self._thread_categories = {thread_id: category for category, thread_id in self._threads.items()}

    def _load_threads(self):
        try:
            return json.loads(THREADS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_threads(self):
        THREADS_FILE.write_text(json.dumps(self._threads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def start(self):
        if self.process and self.process.poll() is None:
            return
        child_env = os.environ.copy()
        for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy"):
            child_env.pop(key, None)
        self.process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=ROOT,
            env=child_env,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request("initialize", {"clientInfo": {"name": "course-studyspace", "title": "课程学习助手", "version": "0.1.0"}}, timeout=15)
        self.notify("initialized", {})

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def _send(self, payload):
        self.start() if self.process is None else None
        line = json.dumps(payload, ensure_ascii=False)
        with self._write_lock:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()

    def request(self, method, params, timeout=30):
        request_id = self._next_id
        self._next_id += 1
        result_queue = queue.Queue(maxsize=1)
        self._pending[request_id] = result_queue
        self._send({"id": request_id, "method": method, "params": params})
        try:
            response = result_queue.get(timeout=timeout)
        finally:
            self._pending.pop(request_id, None)
        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result")

    def notify(self, method, params=None):
        payload = {"method": method}
        if params:
            payload["params"] = params
        self._send(payload)

    def _read_stdout(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in message and ("result" in message or "error" in message):
                pending = self._pending.get(message["id"])
                if pending:
                    pending.put(message)
                continue
            if "id" in message and "method" in message:
                self._approval_requests[str(message["id"])] = message
            params = message.get("params") or {}
            thread_id = params.get("threadId") or params.get("thread", {}).get("id")
            category = self._thread_categories.get(thread_id, "system")
            self._events[category].append({"at": time.time(), **message})

    def _read_stderr(self):
        for line in self.process.stderr:
            self._events["system"].append({"at": time.time(), "method": "bridge/stderr", "params": {"text": line.rstrip()}})

    def ensure_thread(self, category: str):
        category_dir = (LIBRARY / category).resolve()
        if not category_dir.is_dir() or category_dir.parent != LIBRARY.resolve():
            raise ValueError("未知课程类别")
        self.start()
        existing = self._threads.get(category)
        if existing:
            try:
                result = self.request("thread/resume", {
                    "threadId": existing,
                    "cwd": str(category_dir),
                    "sandbox": "workspace-write",
                    "approvalPolicy": "on-request",
                }, timeout=30)
                self._thread_categories[existing] = category
                return result
            except RuntimeError:
                pass
        result = self.request("thread/start", {
            "cwd": str(category_dir),
            "sandbox": "workspace-write",
            "approvalPolicy": "on-request",
            "ephemeral": False,
        }, timeout=30)
        thread_id = result["thread"]["id"]
        self._threads[category] = thread_id
        self._thread_categories[thread_id] = category
        self._save_threads()
        return result

    def send_message(self, category: str, text: str, course_id: int | None = None, selection: str = ""):
        result = self.ensure_thread(category)
        thread_id = result["thread"]["id"]
        context = f"当前课程 ID：{course_id}\n" if course_id else ""
        if selection:
            context += f"用户当前划选的课程原文：\n{selection}\n\n"
        prompt = context + text
        return self.request("turn/start", {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
        }, timeout=30)

    def events(self, category: str, since: float = 0):
        return [event for event in self._events[category] if event["at"] > since]

    def answer_approval(self, request_id: str, decision: str):
        if decision not in {"accept", "acceptForSession", "decline", "cancel"}:
            raise ValueError("不支持的授权决定")
        request = self._approval_requests.pop(request_id, None)
        if not request:
            raise ValueError("授权请求不存在或已处理")
        self._send({"id": request["id"], "result": {"decision": decision}})


bridge = CodexBridge()
