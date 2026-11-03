"""The assistant's stream mode (UX5-C1), through the real `bin/nulavio ai assistant` process.

One JSON request line on stdin with "stream": true; one JSON event per line on stdout, exactly one of
them terminal (done or error). SIGTERM, or the end of stdin, cancels: done {cancelled: true, sent}.
The provider is tests/lib/fake_llm.py on 127.0.0.1; no engine runs here.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from fake_llm import FakeProvider, Reply  # noqa: E402
from nulavio_launcher.ai import assistant, audit, registry  # noqa: E402
from test_vault_storage import FAKE_SECRET_TOOL  # noqa: E402

PROFILE = "/home/u/.local/share/nulavio/profiles/pessoal"
TERMINAL = ("done", "error")


class Run:
    """One `nulavio ai assistant` process; its lines are read as they come, with the provider's
    count of streamed pieces at that moment."""

    def __init__(self, request: dict, provider: FakeProvider, env: dict):
        self.provider = provider
        self.proc = subprocess.Popen(
            [str(ROOT / "bin" / "nulavio"), "ai", "assistant"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True,
        )  # fmt: skip
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.proc.stdin.write(json.dumps({**request, "stream": True, "profile": PROFILE}) + "\n")
        self.proc.stdin.flush()
        self.events: list[dict] = []

    def _read(self):
        for line in self.proc.stdout:
            self.lines.put((line, self.provider.pieces_sent))
        self.lines.put((None, None))

    def next(self, timeout: float = 20) -> dict | None:
        line, pieces = self.lines.get(timeout=timeout)
        if line is None:
            return None
        event = json.loads(line)  # every line is one JSON object
        event["_pieces"] = pieces
        self.events.append(event)
        return event

    def until(self, kind: str, timeout: float = 20) -> dict:
        while True:
            event = self.next(timeout)
            if event is None or event["type"] == kind or event["type"] in TERMINAL:
                return event

    def finish(self, timeout: float = 30) -> list[dict]:
        while self.next(timeout) is not None:
            pass
        self.proc.wait(timeout)
        return self.events

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if pipe:
                pipe.close()


class StreamTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="nv-stream-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        tool = self.home / "secret-tool"
        tool.write_text(FAKE_SECRET_TOOL.format(python=sys.executable))
        tool.chmod(0o700)
        env = {"NULAVIO_HOME": str(self.home / "nv"), "NULAVIO_SECRET_TOOL": str(tool),
               "NV_FAKE_KEYRING": str(self.home / "keyring.json")}  # fmt: skip
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        # No desktop: the approval fallback is "no", never a real dialog on this computer.
        self.env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        self.provider = FakeProvider()
        self.addCleanup(self.provider.close)
        self.state = assistant.configure("openai", self.provider.base, "test-model", "Local", "sk-test")
        assistant.allow_profile(PROFILE, True)

    def run_(self, request: dict, env: dict | None = None) -> Run:
        run = Run(request, self.provider, env or self.env)
        self.addCleanup(run.close)
        return run

    def terminal(self, events: list[dict]) -> dict:
        ends = [e for e in events if e["type"] in TERMINAL]
        self.assertEqual(len(ends), 1, events)  # exactly one terminal line
        self.assertIs(events[-1], ends[0])
        return ends[0]

    def test_deltas_arrive_before_the_last_piece(self):
        self.provider.replies.append(Reply(chunks=["Um ", "dois ", "três ", "quatro"], chunk_delay=0.4))
        run = self.run_({"op": "ask", "question": "Conte"})
        start = run.until("start")
        first = run.until("delta")
        self.assertEqual(first["type"], "delta")
        self.assertLess(first["_pieces"], 4)  # shown while the provider is still sending
        done = self.terminal(run.finish())
        deltas = "".join(e["text"] for e in run.events if e["type"] == "delta")
        self.assertEqual((done["answer"], deltas), ("Um dois três quatro", "Um dois três quatro"))
        self.assertEqual((done["cancelled"], done["sent"], done["truncated"]), (False, True, False))
        self.assertEqual(start["chars"], self.provider.chars[-1])  # the size shown is what went
        self.assertEqual(start["recipient"], self.state["recipient"])
        self.assertTrue(self.provider.requests[-1][2]["stream"])
        kinds = [e["type"] for e in run.events]
        self.assertEqual(kinds[:2], ["start", "sending"])
        self.assertEqual(run.proc.returncode, 0)

    def test_split_lines_done_marker_and_anthropic(self):
        self.provider.split_lines = True
        self.provider.replies.append(Reply(chunks=["a", "b", "c"], stop="length"))
        done = self.terminal(self.run_({"op": "ask", "question": "Oi"}).finish())
        self.assertEqual((done["answer"], done["truncated"]), ("abc", True))
        assistant.configure("anthropic", self.provider.base, "test-model", "Local", None)
        self.provider.replies.append(Reply(chunks=["x ", "y"], stop="max_tokens"))
        done = self.terminal(self.run_({"op": "ask", "question": "Oi"}).finish())
        self.assertEqual((done["answer"], done["truncated"]), ("x y", True))
        self.provider.replies.append(Reply(chunks=["meio"], error="overloaded_error"))
        run = self.run_({"op": "ask", "question": "Oi"})
        error = self.terminal(run.finish())
        self.assertEqual((error["type"], error["code"], error["sent"]), ("error", "provider-unavailable", True))
        self.assertEqual("".join(e["text"] for e in run.events if e["type"] == "delta"), "meio")  # what came is kept

    def test_a_server_that_ignores_stream_still_answers(self):
        self.provider.ignore_stream = True
        self.provider.replies.append({"choices": [{"message": {"content": "Inteira"}, "finish_reason": "stop"}]})
        run = self.run_({"op": "ask", "question": "Oi"})
        done = self.terminal(run.finish())
        self.assertEqual(done["answer"], "Inteira")
        self.assertEqual([e["text"] for e in run.events if e["type"] == "delta"], ["Inteira"])

    def test_provider_errors_end_with_one_error_line(self):
        self.provider.replies.append(Reply(status=429, headers={"Retry-After": "7"}))
        error = self.terminal(self.run_({"op": "ask", "question": "Oi"}).finish())
        self.assertEqual(
            (error["code"], error["sent"], error["retryAfter"], error["status"]), ("provider-rate-limited", True, 7, 429)
        )
        error = self.terminal(self.run_({"op": "ask", "question": ""}).finish())
        self.assertEqual((error["code"], error["sent"]), ("bad-question", False))

    def test_sigterm_mid_stream_cancels_after_sending(self):
        self.provider.replies.append(Reply(chunks=["a ", "b ", "c ", "d ", "e"], chunk_delay=0.5))
        run = self.run_({"op": "ask", "question": "Devagar"})
        run.until("delta")
        started = time.monotonic()
        run.proc.send_signal(signal.SIGTERM)
        done = self.terminal(run.finish())
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual((done["type"], done["cancelled"], done["sent"]), ("done", True, True))
        self.assertEqual(run.proc.returncode, 0)
        entries = audit.read(agent=assistant.load()["agent"])
        self.assertEqual(entries[-1]["outcome"], "cancelled")  # it may have left: the activity says so

    def test_sigterm_before_the_request_sends_nothing(self):
        slow = self.home / "slow-secret-tool"  # the key lookup comes just before the request goes
        slow.write_text(f'#!/bin/sh\nsleep 3\nexec {self.home / "secret-tool"} "$@"\n')
        slow.chmod(0o700)
        run = self.run_({"op": "ask", "question": "Oi"}, env={**self.env, "NULAVIO_SECRET_TOOL": str(slow)})
        self.assertEqual(run.until("start")["type"], "start")
        run.proc.send_signal(signal.SIGTERM)
        done = self.terminal(run.finish())
        self.assertEqual((done["cancelled"], done["sent"]), (True, False))
        self.assertEqual(self.provider.count, 0)
        self.assertNotIn("sending", [e["type"] for e in run.events])

    def test_the_end_of_stdin_cancels(self):
        self.provider.replies.append(Reply(chunks=["a ", "b ", "c"], chunk_delay=0.5))
        run = self.run_({"op": "ask", "question": "Oi"})
        run.until("delta")
        run.proc.stdin.close()  # the browser closed its end, or ended
        done = self.terminal(run.finish())
        self.assertEqual((done["cancelled"], done["sent"]), (True, True))

    def test_a_cancel_during_an_approval_removes_the_request(self):
        """Task mode: the run waits for a permission answer; a cancel ends the wait and its files go."""
        registry.grant(self.state["agent"]["id"], "navigate", "ask")
        call = {
            "id": "c1",
            "type": "function",
            "function": {"name": "tab_new", "arguments": json.dumps({"url": "https://example.invalid/"})},
        }
        self.provider.replies.append({"choices": [{"message": {"content": None, "tool_calls": [call]}}]})
        run = self.run_({"op": "task", "task": "Abra algo"})
        approval = run.until("approval", timeout=30)
        self.assertEqual((approval["type"], approval["capability"]), ("approval", "navigate"))
        request = registry.requests_dir() / f"{approval['id']}.json"
        self.assertTrue(request.exists())
        request.with_suffix(".seen").touch()  # a browser shows it; nobody answers
        started = [e for e in run.events if e["type"] == "step"]
        self.assertEqual([(e["tool"], e["state"]) for e in started], [("tab_new", "started")])
        run.proc.send_signal(signal.SIGTERM)
        done = self.terminal(run.finish())
        self.assertEqual((done["cancelled"], done["sent"]), (True, True))
        self.assertEqual(list(registry.requests_dir().iterdir()), [])  # the request page can no longer answer
        self.assertEqual(self.provider.count, 1)  # no further model turn

    def test_task_steps_say_what_happened_never_the_output(self):
        local = {
            "id": "c1",
            "type": "function",
            "function": {"name": "tab_new", "arguments": json.dumps({"url": "http://127.0.0.1:9/"})},
        }
        self.provider.replies += [{"choices": [{"message": {"content": None, "tool_calls": [local]}}]},
                                  {"choices": [{"message": {"content": "Não deu."}}]}]  # fmt: skip
        run = self.run_({"op": "task", "task": "Abra a página local"})
        done = self.terminal(run.finish())
        steps = [e for e in run.events if e["type"] == "step"]
        self.assertEqual([e["state"] for e in steps], ["started", "denied"])
        self.assertEqual(steps[1]["capability"], "navigate,local_resources")
        self.assertEqual(steps[1]["origin"], "http://127.0.0.1:9")
        self.assertNotIn("Denied by Nulavio", json.dumps(steps))  # the tool's text is the model's, not the panel's
        self.assertEqual([e["turn"] for e in run.events if e["type"] == "sending"], [0, 1])
        self.assertEqual((done["answer"], done["steps"]), ("Não deu.", [{"tool": "tab_new", "error": True}]))

    def test_without_stream_the_contract_is_unchanged(self):
        proc = subprocess.run(
            [str(ROOT / "bin" / "nulavio"), "ai", "assistant"],
            input=json.dumps({"op": "ask", "question": "Oi", "profile": PROFILE}), capture_output=True, text=True,
            env=self.env, timeout=30, check=False,
        )  # fmt: skip
        answer = json.loads(proc.stdout)
        self.assertEqual(answer["answer"], "ok")
        self.assertEqual(proc.stdout.count("\n"), 1)


if __name__ == "__main__":
    unittest.main()
