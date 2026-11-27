"""#788: the unit test classes that drive a Shell module under Node fail, never skip, in CI.

`requires_node` (tests/lib/node_tool.py) skips such a class where `node` is missing, and fails it under
NULAVIO_REQUIRE_NODE=1, which CI's unit job sets. Each class that runs `node` must go through it: a new one
with a decorator of its own would skip silently on a runner without Node (I12).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "lib"))

import node_tool  # noqa: E402
from node_tool import KNOB, requires_node  # noqa: E402

UNIT = ROOT / "tests" / "unit"


def _runs_node(tree: ast.AST) -> bool:
    """A literal argument list that starts with "node", as subprocess.run(["node", ...]) takes it.

    Any such list counts, not only one written inside the call: a data literal like ["node", "edge"] is flagged too,
    on purpose. That over-match fails loudly and names the class; matching only at the call site would miss
    `argv = ["node", ...]; subprocess.run(argv)`, a silent skip, which is what #788 guards against."""
    return any(
        isinstance(n, (ast.List, ast.Tuple)) and n.elts and isinstance(n.elts[0], ast.Constant) and n.elts[0].value == "node"
        for n in ast.walk(tree)
    )


def _calls(tree: ast.AST, names: set[str]) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names for n in ast.walk(tree))


def node_classes(source: str) -> dict[str, bool]:
    """The module's top-level classes that run `node`, directly or through its module-level functions (as
    test_profiles_launch's drive() does), each with whether `requires_node` decorates it."""
    module = ast.parse(source)
    functions = {n.name: n for n in module.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    drivers = {name for name, fn in functions.items() if _runs_node(fn)}
    while True:  # a function that calls a driver drives node too
        more = {name for name, fn in functions.items() if name not in drivers and _calls(fn, drivers)}
        if not more:
            break
        drivers |= more
    found = {}
    for cls in (n for n in module.body if isinstance(n, ast.ClassDef)):
        if _runs_node(cls) or _calls(cls, drivers):
            found[cls.name] = any(isinstance(d, ast.Name) and d.id == "requires_node" for d in cls.decorator_list)
    return found


def _which_node(source: str) -> bool:
    for n in ast.walk(ast.parse(source)):
        first = n.args[:1] + [k.value for k in n.keywords if k.arg == "cmd"] if isinstance(n, ast.Call) else []
        if any(isinstance(a, ast.Constant) and a.value == "node" for a in first):
            func = n.func
            if (isinstance(func, ast.Attribute) and func.attr == "which") or (isinstance(func, ast.Name) and func.id == "which"):
                return True
    return False


class EveryNodeClassUsesTheHelperTest(unittest.TestCase):
    def setUp(self):
        self.found = {}
        for path in sorted(UNIT.glob("test*.py")):
            for name, gated in node_classes(path.read_text(encoding="utf-8")).items():
                self.found[f"{path.name}:{name}"] = gated

    def test_every_class_that_runs_node_is_decorated_with_requires_node(self):
        self.assertEqual([name for name, gated in self.found.items() if not gated], [])

    def test_the_detector_finds_the_eleven_classes_of_788(self):
        """Not vacuous: the eleven classes the issue lists, three of them only through drive(), and #808's one."""
        per_file = {}
        for name in self.found:
            per_file[name.split(":")[0]] = per_file.get(name.split(":")[0], 0) + 1
        known = {
            "test_assistant.py": 3,
            "test_profiles_launch.py": 3,
            "test_lookalike_actors.py": 1,
            "test_lookalike_logins.py": 1,
            "test_shell.py": 1,
            "test_site.py": 1,
            "test_search_alias.py": 1,
            "test_routing_open_in.py": 1,
            "test_name_isolation.py": 1,
        }
        for module, count in known.items():
            with self.subTest(module):
                self.assertGreaterEqual(per_file.get(module, 0), count, self.found)

    def test_no_unit_test_gates_on_node_by_itself(self):
        """shutil.which("node") belongs to the helper only: a decorator of a module's own ignores the knob."""
        self.assertEqual([p.name for p in sorted(UNIT.glob("test*.py")) if _which_node(p.read_text(encoding="utf-8"))], [])

    def test_the_detector_flags_an_undecorated_class_and_leaves_the_rest(self):
        source = (
            "import subprocess, unittest\n"
            "from pathlib import Path\n"
            "def drive(m):\n    return subprocess.run(['node', m])\n"
            "def twice(m):\n    return drive(m)\n"
            "class Direct(unittest.TestCase):\n    def test(self):\n        subprocess.run(('node', '-e', '1'))\n"
            "class Indirect(unittest.TestCase):\n    def test(self):\n        twice('x')\n"
            "@requires_node\nclass Gated(unittest.TestCase):\n    def test(self):\n        drive('x')\n"
            "class Fake(unittest.TestCase):\n    def test(self):\n        Path('fake') / 'node'\n"
            "class Data(unittest.TestCase):\n    def test(self):\n        {'type': 'node'}\n"
        )
        self.assertEqual(node_classes(source), {"Direct": False, "Indirect": False, "Gated": True})
        self.assertTrue(_which_node('import shutil\nshutil.which("node")\n'))
        self.assertTrue(_which_node('import shutil\nNODE = shutil.which(cmd="node")\n'))
        self.assertFalse(_which_node('import shutil\nshutil.which("gpg")\n'))


def _probe() -> type[unittest.TestCase]:
    # Built here so that discovery does not collect it.
    class Probe(unittest.TestCase):
        ran: ClassVar[list[str]] = []

        @classmethod
        def setUpClass(cls):
            cls.ran.append("setUpClass")

        def test_it(self):
            self.ran.append("test")

    return Probe


class RequiresNodeTest(unittest.TestCase):
    def run_probe(self, node: str | None, knob: str | None) -> tuple[unittest.TestResult, list[str]]:
        with mock.patch.dict(os.environ), mock.patch.object(node_tool.shutil, "which", return_value=node) as which:
            os.environ.pop(KNOB, None)
            if knob is not None:
                os.environ[KNOB] = knob
            cls = requires_node(_probe())
        which.assert_called_once_with("node")
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(cls).run(result)
        return result, cls.ran

    def test_with_node_the_class_runs_as_written(self):
        for knob in (None, "1"):
            with self.subTest(knob=knob):
                result, ran = self.run_probe("/usr/bin/node", knob)
                self.assertTrue(result.wasSuccessful())
                self.assertEqual((result.testsRun, len(result.skipped)), (1, 0))
                self.assertEqual(ran, ["setUpClass", "test"])

    def test_without_node_and_without_the_knob_the_class_is_skipped(self):
        for knob in (None, "", "0"):
            with self.subTest(knob=knob):
                result, ran = self.run_probe(None, knob)
                self.assertTrue(result.wasSuccessful())
                self.assertEqual(len(result.skipped), 1)
                self.assertIn(KNOB, result.skipped[0][1])
                self.assertEqual(ran, [])

    def test_without_node_under_the_knob_the_class_fails(self):
        result, ran = self.run_probe(None, "1")
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.skipped, [])
        self.assertEqual(len(result.errors), 1)
        self.assertIn(f"{KNOB}=1 but node is not on PATH", result.errors[0][1])
        self.assertEqual(ran, [])


class ImportsOnItsOwnTest(unittest.TestCase):
    def test_each_module_that_uses_the_helper_imports_without_the_runner(self):
        """site.yml runs `unittest discover -s tests/unit -p test_site.py`, which puts only tests/unit on the path,
        and an empty PATH (no gocryptfs, no node) must not skip a module at import before the knob can fail it."""
        modules = [p.stem for p in sorted(UNIT.glob("test*.py")) if "from node_tool import" in p.read_text(encoding="utf-8")]
        self.assertIn("test_site", modules)
        with tempfile.TemporaryDirectory() as empty:
            env = {"PATH": empty, KNOB: "1"}
            for module in modules:
                with self.subTest(module):
                    code = f"import sys; sys.path.insert(0, {str(UNIT)!r}); import {module}"
                    run = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True, timeout=120)
                    self.assertEqual(run.returncode, 0, run.stderr[-2000:])


class CiRequiresNodeTest(unittest.TestCase):
    def test_the_unit_job_sets_the_knob(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        step = ci.split("      - name: Unit tests\n", 1)[1].split("      - name: ", 1)[0]
        self.assertIn("run: python3 -I tests/run.py unit\n", step)
        self.assertIn(f'{KNOB}: "1"', step)


if __name__ == "__main__":
    unittest.main()
