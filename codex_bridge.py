#!/usr/bin/env python3
"""Small JSON-RPC bridge to the locally installed Codex app-server."""
from __future__ import annotations

import json
import os
import queue
import re
import socket
import subprocess
import threading
import time
import tomllib
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
        self._start_lock = threading.RLock()
        self._thread_lock = threading.Lock()
        self._pending = {}
        self._events = defaultdict(lambda: deque(maxlen=2000))
        self._approval_requests = {}
        self._threads = self._load_threads()
        self._thread_categories = {thread_id: category for category, thread_id in self._threads.items()}
        self._active_threads = set()
        self._model_cache = None
        self._model_cache_at = 0.0

    def _load_threads(self):
        try:
            return json.loads(THREADS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_threads(self):
        THREADS_FILE.write_text(json.dumps(self._threads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def start(self):
        with self._start_lock:
            if self.process and self.process.poll() is None:
                return
            child_env = os.environ.copy()
            # launchd 中可能残留旧代理；优先使用本机当前可连接的 Clash 端口。
            try:
                with socket.create_connection(("127.0.0.1", 7890), timeout=0.15):
                    proxy = "http://127.0.0.1:7890"
                for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy"):
                    child_env[key] = proxy
            except OSError:
                for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy"):
                    if "127.0.0.1:7897" in child_env.get(key, ""):
                        child_env.pop(key, None)
            self._active_threads.clear()
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
        if self.process is None or self.process.poll() is not None:
            self.start()
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
        with self._thread_lock:
            existing = self._threads.get(category)
            if existing in self._active_threads:
                return {"thread": {"id": existing}}
            if existing:
                try:
                    result = self.request("thread/resume", {
                        "threadId": existing,
                        "cwd": str(category_dir),
                        "sandbox": "workspace-write",
                        "approvalPolicy": "on-request",
                    }, timeout=30)
                    self._thread_categories[existing] = category
                    self._active_threads.add(existing)
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
            self._active_threads.add(thread_id)
            self._save_threads()
            return result

    def runtime_info(self):
        config_path = Path.home() / ".codex" / "config.toml"
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            config = {}
        return {
            "model": str(config.get("model") or "未在配置中指定"),
            "reasoning_effort": str(config.get("model_reasoning_effort") or "默认"),
            "transport": "本机 Codex app-server",
        }

    def list_models(self):
        if self._model_cache and time.time() - self._model_cache_at < 300:
            return self._model_cache
        self.start()
        result = self.request("model/list", {"includeHidden": False, "limit": 100}, timeout=30)
        models = [item for item in (result or {}).get("data", []) if not item.get("hidden")]
        self._model_cache = models
        self._model_cache_at = time.time()
        return models

    def direct_answer(self, text: str, model: str | None = None, effort: str | None = None):
        compact = re.sub(r"\s+", "", text).lower()
        if re.search(r"(你|当前|agent)?.{0,5}(什么|哪个|哪一个).{0,4}(模型|model)|你是.{0,8}(模型|gpt)", compact):
            info = self.runtime_info()
            active_model = model or info["model"]
            active_effort = effort or info["reasoning_effort"]
            return (
                f"当前课程 Agent 通过 {info['transport']} 运行；实际配置模型是 "
                f"{active_model}，推理强度是 {active_effort}。"
                "这是从页面选择与本机配置读取的，不采用模型自己的身份自述。"
            )
        return None

    def _course_dir(self, category: str, course_id: int | None):
        if course_id is None:
            return None
        courses_dir = LIBRARY / category / "courses"
        if not courses_dir.is_dir():
            return None
        wanted = str(course_id)
        for metadata_path in courses_dir.glob("*/course.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if str(metadata.get("course_id")) == wanted:
                return metadata_path.parent
        return None

    def send_message(self, category: str, text: str, course_id: int | None = None, selection: str = "", model: str | None = None, effort: str | None = None):
        result = self.ensure_thread(category)
        thread_id = result["thread"]["id"]
        course_dir = self._course_dir(category, course_id)
        context = (
            "你是课程学习 Agent。当前课程资料是回答时可优先使用的额外上下文，不是你的知识边界。\n"
            "当问题涉及课程时，先结合课程文字稿理解老师原意；你也可以使用通用知识解释概念、补充背景、比较观点，或按用户要求执行其他任务。\n"
            "如果补充内容并非老师在本课明确讲过，请清楚区分‘课程内容’与‘补充说明’，不要把外部知识冒充老师原话。\n"
        )
        if course_id:
            context += f"当前课程 ID：{course_id}\n"
        if course_dir:
            context += f"当前课程资料目录：{course_dir}\n"
        if selection:
            context += f"用户当前划选的课程原文：\n{selection}\n\n"
        prompt = context + "\n用户的问题或任务：\n" + text
        params = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
        }
        if model:
            params["model"] = model
        if effort:
            params["effort"] = effort
        return self.request("turn/start", params, timeout=30)

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
