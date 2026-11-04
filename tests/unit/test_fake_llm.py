"""The stand-in model provider itself: what the streaming and error tests of the assistant rely on."""

from __future__ import annotations

import json
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from fake_llm import FakeProvider, Reply


class FakeProviderTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeProvider()
        self.addCleanup(self.fake.close)

    def post(self, path: str, body: dict, timeout: float = 10):
        request = urllib.request.Request(self.fake.base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
        return urllib.request.urlopen(request, timeout=timeout)

    def events(self, response) -> list[tuple[str | None, str]]:
        out, name = [], None
        for raw in response:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                out.append((name, line[6:]))
                name = None
        return out

    def test_plain_replies_and_counting(self):
        self.fake.replies.append({"choices": [{"message": {"content": "olá"}}]})
        body = {"messages": [{"role": "system", "content": "sé"}, {"role": "user", "content": "🙂ab"}]}
        with self.post("/chat/completions", body) as response:
            self.assertEqual(json.load(response)["choices"][0]["message"]["content"], "olá")
        anthropic = {"system": "sé", "messages": [{"role": "user", "content": [{"type": "text", "text": "🙂ab"}]}]}
        with self.post("/v1/messages", anthropic) as response:
            self.assertEqual(json.load(response)["content"][0]["text"], "ok")
        self.assertEqual((self.fake.count, self.fake.chars), (2, [5, 5]))  # code points, not bytes or UTF-16

    def test_openai_stream(self):
        self.fake.replies.append(Reply(chunks=["Um ", "dois"], stop="length"))
        with self.post("/chat/completions", {"stream": True, "messages": []}) as response:
            self.assertEqual(response.headers["Content-Type"], "text/event-stream")
            events = self.events(response)
        self.assertEqual(events[-1], (None, "[DONE]"))
        chunks = [json.loads(d)["choices"][0] for _, d in events[:-1]]
        self.assertEqual("".join(c["delta"].get("content", "") for c in chunks), "Um dois")
        self.assertEqual(chunks[-1]["finish_reason"], "length")

    def test_anthropic_stream_and_its_error_event(self):
        self.fake.replies += [{"content": [{"type": "text", "text": "a b c"}], "stop_reason": "max_tokens"},
                              Reply(chunks=["x"], error="overloaded_error")]  # fmt: skip
        with self.post("/v1/messages", {"stream": True, "messages": []}) as response:
            events = self.events(response)
        deltas = [json.loads(d)["delta"]["text"] for n, d in events if n == "content_block_delta"]
        self.assertEqual(deltas, ["a ", "b ", "c"])  # a plain reply is streamed word by word
        stop = [json.loads(d)["delta"]["stop_reason"] for n, d in events if n == "message_delta"]
        self.assertEqual(stop, ["max_tokens"])
        with self.post("/v1/messages", {"stream": True, "messages": []}) as response:
            events = self.events(response)
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(json.loads(events[-1][1])["error"]["type"], "overloaded_error")

    def test_ignore_stream_answers_json(self):
        self.fake.ignore_stream = True
        self.fake.replies.append(Reply(chunks=["só ", "json"]))
        with self.post("/chat/completions", {"stream": True, "messages": []}) as response:
            self.assertEqual(response.headers["Content-Type"], "application/json")
            self.assertEqual(json.load(response)["choices"][0]["message"]["content"], "só json")

    def test_status_and_headers(self):
        self.fake.replies.append(Reply(status=429, headers={"Retry-After": "30"}))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/chat/completions", {"messages": []})
        self.assertEqual((caught.exception.code, caught.exception.headers["Retry-After"]), (429, "30"))
        self.assertIn("error", json.loads(caught.exception.read()))

    def test_pieces_are_spaced_and_counted(self):
        self.fake.replies.append(Reply(chunks=["a", "b", "c"], chunk_delay=0.3))
        seen = []
        with self.post("/chat/completions", {"stream": True, "messages": []}) as response:
            response.readline()  # the first event's data line
            seen.append(self.fake.pieces_sent)
            self.events(response)
        self.assertEqual((seen[0] < 3, self.fake.pieces_sent), (True, 3))

    def test_hang_until_closed(self):
        self.fake.replies.append(Reply(hang=True))
        started = time.monotonic()
        with self.assertRaises((TimeoutError, OSError)):
            self.post("/chat/completions", {"messages": []}, timeout=0.5)
        self.assertLess(time.monotonic() - started, 5)  # close() (the cleanup) releases the held request


if __name__ == "__main__":
    unittest.main()
