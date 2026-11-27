"""The Shell's check in front of the engine's own profile launches, under Node (tests/lib/profiles_launch_driver.mjs).

The engine's app menu and menu bar Profiles lists and "Move tab to profile" start another profile through
SelectableProfileService.launchInstance, which NulavioProfiles.guardLaunches wraps: a locked protected profile gets
the unlock page instead, an engine an agent drives starts no other profile at all, and the addresses a tab is moved
with carry the routed flag, so the other profile's rules do not send them back (#715). The real engine runs the
same menus in tests/integration/test_vault_profiles.py and tests/integration/test_routing.py.

In an engine an agent drives, the engine's other ways of starting a profile are closed too: the chooser opened from
such a window (patch 0011 asks chooser.mjs before every launch) refuses before it reads or unlocks anything
(tests/lib/chooser_launch_driver.mjs), and the Shell's start blocks about:profiles and switches off restoring a
backup, both of which start a profile through Services.startup.createInstanceWithProfile, before it tells the Bridge
the engine is ready (tests/lib/agent_engine_driver.mjs).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from node_tool import requires_node  # noqa: E402

MODULE = ROOT / "browser" / "shell" / "modules" / "NulavioProfiles.sys.mjs"
CHOOSER = ROOT / "browser" / "shell" / "chooser" / "chooser.mjs"
AGENT_NETWORK = ROOT / "browser" / "shell" / "modules" / "NulavioAgentNetwork.sys.mjs"
ROUTER = ROOT / "browser" / "shell" / "modules" / "NulavioRouter.sys.mjs"
# The flag NulavioRouting.handleCommandLine takes as "sent by routing or by an explicit choice: open here".
ROUTED_FLAG = re.search(r'export const ROUTED_FLAG = "([^"]+)";', ROUTER.read_text(encoding="utf-8")).group(1)
# With it, who sent the command line: "explicit" means the person chose the profile, so its band credits no rule.
ROUTE_BY_FLAG = re.search(r'export const ROUTE_BY_FLAG = "([^"]+)";', ROUTER.read_text(encoding="utf-8")).group(1)
EXPLICIT = [f"--{ROUTED_FLAG}", f"--{ROUTE_BY_FLAG}", "explicit"]


def drive(driver: str, module: Path, *extra: str) -> dict:
    done = subprocess.run(
        ["node", str(ROOT / "tests" / "lib" / driver), str(module), *extra],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(done.stdout)


@requires_node
class ProfilesLaunchGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = drive("profiles_launch_driver.mjs", MODULE, ROUTED_FLAG, ROUTE_BY_FLAG)

    def test_a_profile_without_a_password_starts_as_the_engine_meant(self):
        self.assertEqual(self.cases["plain"], {"launched": 1, "sent": [], "started": [], "unlockPages": 0, "logged": []})

    def test_a_moved_tab_reaches_the_running_profile_with_the_routed_flag(self):
        """#715: "Move tab to profile" is the person's explicit choice, first in ADR 0003's precedence (R21). The
        addresses go to the running instance as the engine sends them, behind the flag that routing never moves."""
        case = self.cases["moved_running"]
        self.assertEqual(case["launched"], 0, case)
        self.assertEqual(case["started"], [], case)
        self.assertEqual(case["unlockPages"], 0, case)
        self.assertEqual(case["logged"], [], case)
        args = [*EXPLICIT, "-new-tab", "https://example.org/a", "-new-tab", "https://example.org/b"]
        self.assertEqual(case["sent"], [{"path": "/profiles/other", "args": args, "activate": True}], case)

    def test_a_moved_tab_starts_a_profile_that_is_not_running_with_the_routed_flag(self):
        """No running instance: a new engine on the profile's folder, an argument list with the same flag."""
        case = self.cases["moved_cold"]
        self.assertEqual(case["launched"], 0, case)
        self.assertEqual(case["sent"], [], case)
        args = ["--profile", "/profiles/other", *EXPLICIT, "-new-tab", "https://example.org/moved"]
        self.assertEqual(case["started"], [args], case)

    def test_a_moved_tab_to_an_unlocked_protected_profile_carries_the_flag_too(self):
        case = self.cases["moved_unlocked"]
        self.assertEqual(case["launched"], 0, case)
        self.assertEqual(case["unlockPages"], 0, case)
        self.assertEqual([s["args"][:3] for s in case["sent"]], [EXPLICIT], case)

    def test_a_locked_or_unreadable_profile_gets_the_unlock_page_and_no_engine(self):
        for name in ("locked", "unreadable"):
            with self.subTest(name):
                self.assertEqual(self.cases[name]["launched"], 0)
                self.assertEqual(self.cases[name]["sent"], [])
                self.assertEqual(self.cases[name]["started"], [])
                self.assertEqual(self.cases[name]["unlockPages"], 1)

    def test_an_engine_an_agent_drives_starts_no_other_profile_from_the_engines_menus(self):
        """The same refusal as switchTo and openTemporary (agent-window), whatever the other profile's lock state:
        a started engine would inherit the agent's environment, and the unlock page would lead to one."""
        for name in ("agent_plain", "agent_unlocked", "agent_locked"):
            with self.subTest(name):
                case = self.cases[name]
                self.assertEqual(case["launched"], 0, case)
                self.assertEqual(case["sent"], [], case)
                self.assertEqual(case["started"], [], case)
                self.assertEqual(case["unlockPages"], 0, case)
                self.assertEqual(case["logged"], ["Nulavio profiles: launch agent-window"], case)


@requires_node
class ChooserLaunchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = drive("chooser_launch_driver.mjs", CHOOSER)

    def test_a_person_s_chooser_starts_a_plain_profile_and_asks_for_a_locked_one_s_secret(self):
        self.assertEqual(self.cases["plain"]["answer"], True)
        self.assertEqual(self.cases["plain"]["dialogs"], [])
        locked = self.cases["locked"]
        self.assertEqual(locked["helper"], ["status"])
        self.assertEqual(locked["dialogs"], [{"headline": "nulavio-chooser-headline", "password": True}])
        self.assertEqual(locked["answer"], False)  # the person went back

    def test_in_an_engine_an_agent_drives_the_chooser_refuses_before_it_reads_or_unlocks_anything(self):
        """Patch 0011 runs beforeLaunch before the engine's guarded launchInstance: a locked profile would be unlocked
        there and then left without an engine. Refused first, whatever the profile's lock state, with a notice."""
        for name in ("agent_plain", "agent_locked"):
            with self.subTest(name):
                case = self.cases[name]
                self.assertEqual(case["answer"], False, case)
                self.assertEqual(case["reads"], 0, case)
                self.assertEqual(case["helper"], [], case)
                self.assertEqual(case["dialogs"], [{"headline": "nulavio-chooser-agent-headline", "password": False}], case)
                self.assertEqual(case["logged"], ["Nulavio chooser: launch agent-window"], case)


@requires_node
class AgentEngineProfilePagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = drive("agent_engine_driver.mjs", AGENT_NETWORK)

    def test_a_person_s_engine_is_left_as_it_is(self):
        self.assertEqual(self.cases["person"], {"armed": False, "events": [], "values": {}})

    def test_an_agent_s_engine_blocks_about_profiles_and_restoring_before_the_bridge_may_use_it(self):
        """about:profiles' "Launch profile in new browser" and restoring a backup start a profile through
        Services.startup.createInstanceWithProfile, which no check of the Shell's stands in front of."""
        case = self.cases["agent"]
        events = case["events"]
        self.assertIs(case["armed"], True)
        self.assertIn("block about:profiles", events)
        self.assertIs(case["values"]["browser.backup.restore.enabled"], False)
        restore = "browser.backup.restore.enabled"
        self.assertLess(events.index(f"default {restore}=false"), events.index(f"lock {restore}"))
        # A tab already at the page (either address) is loaded again, so the block reaches it; other tabs are left.
        self.assertEqual(
            [e for e in events if e.startswith("reload ")],
            ["reload about:profiles", "reload chrome://global/content/aboutProfiles.xhtml"],
        )
        # All of it before READY_FILE, the Bridge's sign that the engine may be used.
        self.assertEqual(events[-1], "write /profile/nulavio-ai-guard")

    def test_an_engine_where_restoring_is_locked_on_is_never_used_for_an_agent(self):
        case = self.cases["agent_restore_locked_on"]
        self.assertEqual(case["armed"], "error: browser.backup.restore.enabled is locked to another value")
        self.assertFalse([e for e in case["events"] if e.startswith("write ")])


if __name__ == "__main__":
    unittest.main()
