import importlib.util
import os
import subprocess
import sys
import threading
import time
import unittest
from collections import deque
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import course_pipeline
import terminal_bridge


def load_launcher_module():
    path = ROOT / "native-host" / "course_server_launcher.py"
    spec = importlib.util.spec_from_file_location("course_server_launcher", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self.exit_code = -15


class FakeSession:
    def __init__(self, updated_at, exit_code=None):
        self.updated_at = updated_at
        self.process = FakeProcess(exit_code)
        self.closed = False

    def close(self):
        self.closed = True
        self.process.terminate()


class CategoryCompatibilityTests(unittest.TestCase):
    def test_legacy_ai_category_is_normalized(self):
        self.assertEqual(course_pipeline.normalize_course_category("AI课"), "AI课-Agent版")

    def test_reviewed_categories_are_unchanged(self):
        self.assertEqual(course_pipeline.normalize_course_category("AI课-Chat版"), "AI课-Chat版")
        self.assertEqual(course_pipeline.normalize_course_category("写作课"), "写作课")

    def test_transcription_payload_is_normalized_before_validation(self):
        payload = course_pipeline.validate_transcription_payload({
            "course_url": "https://webapp.songy.info/#/courses/details?course_id=818",
            "course_category": "AI课",
            "items": [{"category": "audio", "url": "https://media.example/818.m4a"}],
        })
        self.assertEqual(payload["course_category"], "AI课-Agent版")

    def test_transcription_payload_rejects_missing_media_list(self):
        with self.assertRaisesRegex(ValueError, "课程地址或内容"):
            course_pipeline.validate_transcription_payload({"course_url": "https://example.test/818"})


class NativeLauncherEnvironmentTests(unittest.TestCase):
    def test_dead_inherited_proxy_is_removed(self):
        launcher = load_launcher_module()
        inherited = {
            "HOME": "/Users/test",
            "HTTP_PROXY": "http://127.0.0.1:7890",
            "https_proxy": "http://127.0.0.1:7890",
        }
        child = launcher.build_server_environment(inherited)
        for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            self.assertNotIn(key, child)

    def test_server_environment_has_cli_paths_and_idle_limit(self):
        launcher = load_launcher_module()
        child = launcher.build_server_environment({"HOME": "/Users/test"})
        self.assertIn("/usr/local/bin", child["PATH"].split(os.pathsep))
        self.assertIn("/opt/homebrew/bin", child["PATH"].split(os.pathsep))
        self.assertEqual(child["COURSE_SERVER_IDLE_SECONDS"], "120")


class ModelMemoryTests(unittest.TestCase):
    def test_accelerator_cache_is_explicitly_cleared(self):
        import runtime_resources

        class FakeMlxCore:
            cleared = False

            @classmethod
            def clear_cache(cls):
                cls.cleared = True

        runtime_resources.release_accelerator_cache(FakeMlxCore)
        self.assertTrue(FakeMlxCore.cleared)

    def test_course_job_releases_model_memory_in_finally(self):
        source = (ROOT / "local_server.py").read_text(encoding="utf-8")
        job = source[source.index("def run_course_job") : source.index("def run_enhancement_job")]
        self.assertIn("finally:", job)
        self.assertIn("release_transcription_memory()", job)


class EnhancementRetryTests(unittest.TestCase):
    def test_transient_codex_step_retries_only_failed_operation(self):
        attempts = []

        def operation():
            attempts.append(len(attempts) + 1)
            if len(attempts) == 1:
                raise RuntimeError("Codex 超过 6 分钟安全上限")
            return {"ok": True}

        self.assertEqual(course_pipeline.retry_codex_step(operation, attempts=2), {"ok": True})
        self.assertEqual(attempts, [1, 2])

    def test_codex_step_stops_after_retry_budget(self):
        attempts = []

        def operation():
            attempts.append(1)
            raise RuntimeError("并行润色返回不完整")

        with self.assertRaisesRegex(RuntimeError, "返回不完整"):
            course_pipeline.retry_codex_step(operation, attempts=2)
        self.assertEqual(len(attempts), 2)


class TerminalEnvironmentTests(unittest.TestCase):
    def test_chrome_terminal_can_find_node_and_codex(self):
        child = terminal_bridge.build_terminal_environment({"HOME": "/Users/test", "PATH": "/usr/bin"})
        paths = child["PATH"].split(os.pathsep)
        self.assertEqual(paths[0], "/Users/test/.npm-global/bin")
        self.assertIn("/usr/local/bin", paths)
        self.assertEqual(child["TERM"], "xterm-256color")

    def test_live_terminal_prevents_idle_shutdown(self):
        bridge = terminal_bridge.TerminalBridge()
        session = FakeSession(time.time())
        bridge._sessions["live"] = session
        bridge._course_sessions["818"] = "live"
        self.assertTrue(bridge.has_active_sessions(stale_after=180))
        self.assertFalse(session.closed)

    def test_abandoned_terminal_is_reaped(self):
        bridge = terminal_bridge.TerminalBridge()
        session = FakeSession(time.time() - 181)
        bridge._sessions["stale"] = session
        bridge._course_sessions["818"] = "stale"
        self.assertFalse(bridge.has_active_sessions(stale_after=180))
        self.assertTrue(session.closed)
        self.assertNotIn("stale", bridge._sessions)
        self.assertNotIn("818", bridge._course_sessions)

    def test_reopening_same_course_reuses_live_terminal(self):
        bridge = terminal_bridge.TerminalBridge()
        session = FakeSession(time.time())
        session.cwd = ROOT
        session.resize = lambda cols, rows: None
        bridge._sessions["live"] = session
        bridge._course_sessions["818"] = "live"
        reopened = bridge.start("818", ROOT, 80, 24, force=False)
        self.assertIs(reopened, session)


class ExtensionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content_path = ROOT / "extension" / "content.js"
        cls.content = cls.content_path.read_text(encoding="utf-8")

    def test_content_script_has_valid_javascript(self):
        result = subprocess.run(
            ["node", "--check", str(self.content_path)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_terminal_does_not_poll_every_60ms(self):
        self.assertNotIn("setTimeout(pollNativeTerminal, 60)", self.content)
        self.assertIn("nativeTerminalIdlePolls", self.content)

    def test_terminal_stops_polling_after_exit(self):
        self.assertIn('nativeTerminalSessionId = "";', self.content)
        self.assertIn("keepPolling = false", self.content)

    def test_old_ai_category_is_not_a_selectable_option(self):
        self.assertNotIn("<option>AI课</option>", self.content)
        self.assertIn("<option>AI课-Agent版</option>", self.content)
        self.assertIn("<option>AI课-Chat版</option>", self.content)

    def test_reopening_course_loads_saved_transcript(self):
        self.assertIn("identifyCourseCategory().finally(loadTranscript)", self.content)
        self.assertIn("/transcript?url=", self.content)

    def test_switching_course_cancels_previous_terminal_poll(self):
        course_change = self.content[self.content.index("function handleCourseChange()") :]
        self.assertIn("clearTimeout(nativeTerminalPollTimer)", course_change[:1800])


if __name__ == "__main__":
    unittest.main()
