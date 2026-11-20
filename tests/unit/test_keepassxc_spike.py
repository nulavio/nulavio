"""The KeePassXC native-messaging step presses Connect again when the association dialog does not come (#498)."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("kpx_spike", ROOT / "scripts" / "research" / "keepassxc_native_messaging_spike.py")
spike = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spike)

NOT_CONFIGURED = {"text": "Not configured", "buttons": [{"id": "c", "text": "Connect"}]}


def instant_wait(predicate, timeout=0.0, interval=0.0):
    return predicate()


class ConnectUntilDialogTest(unittest.TestCase):
    def run_flow(self, dialog_after_press: int | None, popups=None, attempts: int = 4):
        """Dialog opens on the Nth press of Connect (None: never)."""
        presses = []
        popups = list(popups or [])

        def open_popup():
            return popups.pop(0) if popups else NOT_CONFIGURED

        def press(state):
            if not any("connect" in b["text"].lower() for b in state["buttons"]):
                return False
            presses.append(1)
            return True

        def seen():
            return dialog_after_press is not None and len(presses) >= dialog_after_press

        with mock.patch.object(spike.harness, "wait_until", instant_wait):
            return spike.connect_until_dialog(open_popup, press, seen, attempts=attempts, wait=0), len(presses)

    def test_first_press_is_enough(self):
        result, presses = self.run_flow(1)
        self.assertEqual((result["answered"], result["attempts"], presses), (True, 1, 1))

    def test_lost_press_is_repeated(self):
        result, presses = self.run_flow(3)
        self.assertEqual((result["answered"], result["attempts"], presses), (True, 3, 3))
        self.assertIn("no dialog", result["log"][0])

    def test_popup_without_connect_button_is_reopened(self):
        bare = {"text": "Checking", "buttons": []}
        result, presses = self.run_flow(1, popups=[bare, bare])
        self.assertEqual((result["answered"], result["attempts"], presses), (True, 3, 1))
        self.assertIn("no Connect button", result["log"][0])

    def test_gives_up_and_says_so(self):
        result, presses = self.run_flow(None, attempts=3)
        self.assertEqual((result["answered"], result["attempts"], presses), (False, 3, 3))


class WatcherTest(unittest.TestCase):
    def test_dialog_renamed_after_opening_is_still_answered(self):
        watcher = spike.DialogWatcher({})
        calls = []
        rounds = iter([{"7": "KeePassXC"}, {"7": "KeePassXC - Association"}, {"7": "KeePassXC - Association"}])

        def windows():
            try:
                return next(rounds)
            except StopIteration:
                watcher.stop.set()
                return {}

        watcher.windows = windows
        with (
            mock.patch.object(spike, "run", lambda cmd, **kw: calls.append(cmd)),
            mock.patch.object(spike.time, "sleep", lambda s: None),
        ):
            watcher.run()
        self.assertEqual(len(watcher.actions), 1)
        self.assertEqual(watcher.titles, {"KeePassXC", "KeePassXC - Association"})


if __name__ == "__main__":
    unittest.main()
