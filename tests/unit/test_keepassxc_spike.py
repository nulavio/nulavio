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
    def run_flow(self, dialog_after_press: int | None, popups=None, attempts: int = 4, answered_before: int = 0):
        """Dialog opens on the Nth press of Connect (None: never); `answered_before` dialogs were answered earlier."""
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
            opened = dialog_after_press is not None and len(presses) >= dialog_after_press
            return answered_before + (1 if opened else 0)

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

    def test_dialog_answered_earlier_does_not_satisfy_a_later_press(self):
        result, presses = self.run_flow(None, attempts=3, answered_before=1)
        self.assertEqual((result["answered"], result["attempts"], presses), (False, 3, 3))

    def test_gives_up_and_says_so(self):
        result, presses = self.run_flow(None, attempts=3)
        self.assertEqual((result["answered"], result["attempts"], presses), (False, 3, 3))


class SettlePopupTest(unittest.TestCase):
    def settle(self, states, max_reloads=4):
        states = list(states)
        log = []
        with mock.patch.object(spike.time, "sleep", lambda s: None):
            result = spike.settle_popup(
                lambda: states.pop(0), lambda i: log.append(("reload", i)), lambda: log.append("close"), max_reloads=max_reloads
            )
        return result, log

    def test_reload_is_pressed_until_connect_shows(self):
        cannot = {"text": "Cannot connect to KeePassXC", "buttons": [{"id": "reload-status-button", "text": "Reload"}]}
        result, log = self.settle([cannot, cannot, NOT_CONFIGURED])
        self.assertEqual(result["reloads"], 2)
        self.assertEqual(result["buttons"], NOT_CONFIGURED["buttons"])
        self.assertEqual(log, [("reload", "reload-status-button"), "close"] * 2)

    def test_stops_at_the_limit(self):
        cannot = {"text": "Cannot connect", "buttons": [{"id": "reload-status-button", "text": "Reload"}]}
        result, _ = self.settle([cannot] * 3, max_reloads=2)
        self.assertEqual(result["reloads"], 2)

    def test_connected_popup_is_left_alone(self):
        result, log = self.settle([{"text": "Nulavio is connected", "buttons": []}])
        self.assertEqual((result["reloads"], log), (0, []))


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

    def test_answered_window_renamed_again_is_not_answered_twice(self):
        watcher = spike.DialogWatcher({})
        rounds = iter([{"7": "KeePassXC - Association"}, {"7": "KeePassXC - Associate key"}, {"7": "KeePassXC - Associate key"}])

        def windows():
            try:
                return next(rounds)
            except StopIteration:
                watcher.stop.set()
                return {}

        watcher.windows = windows
        with (
            mock.patch.object(spike, "run", lambda cmd, **kw: None),
            mock.patch.object(spike.time, "sleep", lambda s: None),
        ):
            watcher.run()
        self.assertEqual(len(watcher.actions), 1)


if __name__ == "__main__":
    unittest.main()
