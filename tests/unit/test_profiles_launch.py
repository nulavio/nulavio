"""The Shell's check in front of the engine's own profile launches, under Node (tests/lib/profiles_launch_driver.mjs).

The engine's app menu and menu bar Profiles lists and "Move tab to profile" start another profile through
SelectableProfileService.launchInstance, which NulavioProfiles.guardLaunches wraps: a locked protected profile gets
the unlock page instead, and an engine an agent drives starts no other profile at all. The real engine runs the
same menus in tests/integration/test_vault_profiles.py.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "browser" / "shell" / "modules" / "NulavioProfiles.sys.mjs"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ProfilesLaunchGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        driver = ROOT / "tests" / "lib" / "profiles_launch_driver.mjs"
        done = subprocess.run(["node", str(driver), str(MODULE)], capture_output=True, text=True, timeout=60, check=True)
        cls.cases = json.loads(done.stdout)

    def test_a_profile_without_a_password_starts_as_the_engine_meant(self):
        self.assertEqual(self.cases["plain"], {"launched": 1, "unlockPages": 0, "logged": []})

    def test_a_locked_or_unreadable_profile_gets_the_unlock_page_and_no_engine(self):
        for name in ("locked", "unreadable"):
            with self.subTest(name):
                self.assertEqual(self.cases[name]["launched"], 0)
                self.assertEqual(self.cases[name]["unlockPages"], 1)

    def test_an_engine_an_agent_drives_starts_no_other_profile_from_the_engines_menus(self):
        """The same refusal as switchTo and openTemporary (agent-window), whatever the other profile's lock state:
        a started engine would inherit the agent's environment, and the unlock page would lead to one."""
        for name in ("agent_plain", "agent_unlocked", "agent_locked"):
            with self.subTest(name):
                case = self.cases[name]
                self.assertEqual(case["launched"], 0, case)
                self.assertEqual(case["unlockPages"], 0, case)
                self.assertEqual(case["logged"], ["Nulavio profiles: launch agent-window"], case)


if __name__ == "__main__":
    unittest.main()
