"""#833: a unit test that starts this Python with an environment of its own keeps what the interpreter needs.

tests/lib/child_env.py builds such an environment. The first class shows why, with an interpreter that starts only
when LD_LIBRARY_PATH names its library directory, as a relocated or self-built Python does. The second checks that
every unit test that starts `sys.executable` with an environment of its own builds it through `child_env`. It
reads the calls (`subprocess.run([sys.executable, ...], env=...)`), so it does not see a child that reaches this
Python through a `#!` line naming it (the fake secret-tool of test_vault.py), and those keep using the helper by
review.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
UNIT = ROOT / "tests" / "unit"
sys.path.insert(0, str(ROOT / "tests" / "lib"))

from child_env import child_env  # noqa: E402

LOADER_FAILS = "error while loading shared libraries: libpython3.so: cannot open shared object file"
SHOW_ENV = "import json, os; print(json.dumps(dict(os.environ)))"


class ChildEnvTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp(prefix="nv-child-env-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        self.libs = tmp / "lib dir"  # where this interpreter's libpython would be
        self.libs.mkdir()
        # Stands for a Python whose libpython the loader finds only through LD_LIBRARY_PATH: it stops as the
        # loader does when the directory is not there, and otherwise runs this Python.
        self.python = tmp / "python"
        libs, python = shlex.quote(str(self.libs)), shlex.quote(sys.executable)
        self.python.write_text(
            f'case ":${{LD_LIBRARY_PATH-}}:" in *:{libs}:*) exec {python} "$@" ;; esac\n'
            f"echo {shlex.quote(LOADER_FAILS)} >&2\nexit 127\n"
        )
        # Added to what this process already has: a Python that needs it is the case this covers.
        here = os.environ.get("LD_LIBRARY_PATH")
        self.ld = f"{here}:{self.libs}" if here else str(self.libs)

    def start(self, env: dict) -> subprocess.CompletedProcess:
        # Read by /bin/sh rather than executed, so a temporary directory mounted noexec still runs it.
        command = ["/bin/sh", str(self.python), "-I", "-c", SHOW_ENV]
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)

    # The stand-in models the GNU loader (LD_LIBRARY_PATH). On macOS a protected /bin/sh would drop the DYLD_*
    # variables before the exec, so it would not show what the helper keeps; the suite runs on Linux.
    @unittest.skipUnless(sys.platform.startswith("linux"), "models the Linux dynamic loader")
    def test_the_interpreter_starts_with_the_helper_and_not_without_it(self):
        own = {"PATH": "/usr/bin:/bin", "NV_CHILD": "1"}
        with mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": self.ld, "NV_PARENT_ONLY": "secret"}):
            bare = self.start(own)
            self.assertEqual(bare.returncode, 127, bare.stdout)
            self.assertIn(LOADER_FAILS, bare.stderr)
            kept = self.start(child_env(own))
        self.assertEqual(kept.returncode, 0, kept.stderr)
        seen = json.loads(kept.stdout)
        self.assertEqual((seen["LD_LIBRARY_PATH"], seen["PATH"], seen["NV_CHILD"]), (self.ld, "/usr/bin:/bin", "1"))
        self.assertNotIn("NV_PARENT_ONLY", seen)  # nothing else from the parent

    def test_only_the_loader_variables_the_parent_has_and_the_caller_does_not_name(self):
        loader = {"LD_LIBRARY_PATH": "/a", "DYLD_LIBRARY_PATH": "/b", "DYLD_FALLBACK_LIBRARY_PATH": "/c"}
        with mock.patch.dict(os.environ, {**loader, "HOME": "/home/x", "PYTHONPATH": "/p", "LD_PRELOAD": "/x.so"}):
            self.assertEqual(child_env({"PATH": "/bin"}), {**loader, "PATH": "/bin"})
            self.assertEqual(child_env({"LD_LIBRARY_PATH": "/own"})["LD_LIBRARY_PATH"], "/own")
            for name in loader:
                os.environ.pop(name)
            self.assertEqual(child_env({"PATH": "/bin"}), {"PATH": "/bin"})  # never an empty one


def _is_executable(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "executable" and isinstance(node.value, ast.Name) \
        and node.value.id == "sys"  # fmt: skip


def _is_environ(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "environ" and isinstance(node.value, ast.Name) \
        and node.value.id == "os"  # fmt: skip


FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
KWARGS = "kwargs"  # a `**name` parameter: a dict of the values named in the call, built from scratch


class _Module:
    """What one test file's calls start and with which environment, read from its source."""

    def __init__(self, source: str):
        self.tree = ast.parse(source)
        self.parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node

    def _ancestors(self, node: ast.AST):
        while node in self.parent:
            node = self.parent[node]
            yield node

    @staticmethod
    def _own(scope: ast.AST):
        """The nodes of `scope` outside the functions and classes defined in it."""
        todo = list(ast.iter_child_nodes(scope))
        while todo:
            node = todo.pop()
            yield node
            if not isinstance(node, (*FUNCTIONS, ast.ClassDef)):
                todo.extend(ast.iter_child_nodes(node))

    @classmethod
    def _assignments(cls, scope: ast.AST, nodes=None):
        for node in cls._own(scope) if nodes is None else nodes:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    yield target, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                yield node.target, node.value
            elif isinstance(node, (ast.For, ast.AsyncFor)):  # over a literal: each element is a value of the target
                literal = isinstance(node.iter, (ast.List, ast.Tuple, ast.Set))
                for value in node.iter.elts if literal else [node.iter]:
                    yield node.target, value

    def assigned(self, target: ast.AST) -> list[ast.AST] | str:
        """What the name or `self.x` attribute `target` holds: the values the nearest scope that has it gives it,
        or KWARGS, or "parameter" (not followed)."""
        if isinstance(target, ast.Name):
            for scope in [*(n for n in self._ancestors(target) if isinstance(n, FUNCTIONS)), self.tree]:
                if isinstance(scope, FUNCTIONS):
                    a = scope.args
                    if a.kwarg is not None and a.kwarg.arg == target.id:
                        return KWARGS
                    if target.id in {p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg) if p}:
                        return "parameter"
                values = [v for n, v in self._assignments(scope) if isinstance(n, ast.Name) and n.id == target.id]
                if values:
                    return values
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
            klass = next((n for n in self._ancestors(target) if isinstance(n, ast.ClassDef)), None)
            if klass is not None:  # `self.x = ...` in its methods, or `x = ...` in the class body
                return [v for n, v in self._assignments(klass, ast.walk(klass)) if isinstance(n, ast.Attribute)
                        and n.attr == target.attr and isinstance(n.value, ast.Name) and n.value.id == "self"] + \
                    [v for n, v in self._assignments(klass) if isinstance(n, ast.Name) and n.id == target.attr]  # fmt: skip
        return []

    def starts_python(self, expr: ast.AST, seen: frozenset = frozenset()) -> bool:
        """Whether `expr` (a call's command) holds sys.executable, through the names it uses."""
        for node in ast.walk(expr):
            if _is_executable(node):
                return True
            if isinstance(node, (ast.Name, ast.Attribute)) and ast.dump(node) not in seen:
                values = self.assigned(node)
                if isinstance(values, list) and any(self.starts_python(v, seen | {ast.dump(node)}) for v in values):
                    return True
        return False

    @staticmethod
    def _either(results) -> bool | None:
        """Built if one of them is, from the parent if all are, else not known."""
        results = list(results)
        return True if True in results else False if all(r is False for r in results) else None

    def built(self, expr: ast.AST, seen: frozenset = frozenset()) -> bool | None:
        """True for an environment made from scratch, False for the parent's (os.environ) or child_env's, None for
        what this does not follow (a parameter, another function's result)."""
        if isinstance(expr, ast.Call):
            name = expr.func.attr if isinstance(expr.func, ast.Attribute) else getattr(expr.func, "id", None)
            if name == "child_env" or (isinstance(expr.func, ast.Attribute) and name == "copy" and _is_environ(expr.func.value)):
                return False
            if name == "dict":
                return self.built(expr.args[0], seen) if expr.args else True
            return None
        if isinstance(expr, ast.Dict):  # from the parent if one spread is; built if every spread is
            spreads = [self.built(v, seen) for k, v in zip(expr.keys, expr.values, strict=True) if k is None]
            return False if False in spreads else None if None in spreads else True
        if isinstance(expr, ast.BoolOp):
            return self._either(self.built(v, seen) for v in expr.values)
        if isinstance(expr, ast.IfExp):
            return self._either((self.built(expr.body, seen), self.built(expr.orelse, seen)))
        if _is_environ(expr) or (isinstance(expr, ast.Constant) and expr.value is None):
            return False
        if isinstance(expr, (ast.Name, ast.Attribute)) and ast.dump(expr) not in seen:
            values = self.assigned(expr)
            if values == KWARGS:
                return True
            if isinstance(values, list) and values:
                return self._either(self.built(v, seen | {ast.dump(expr)}) for v in values)
        return None

    def offending_lines(self) -> list[int]:
        """The calls that start sys.executable with an environment built from scratch, not through child_env."""
        lines = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            env = next((k.value for k in node.keywords if k.arg == "env"), None)
            if env is not None and self.starts_python(node.args[0]) and self.built(env) is True:
                lines.append(node.lineno)
        return sorted(lines)


def offending_lines(source: str) -> list[int]:
    return _Module(textwrap.dedent(source)).offending_lines()


class EveryUnitTestUsesTheHelperTest(unittest.TestCase):
    def test_no_unit_test_starts_this_python_with_an_environment_built_without_the_helper(self):
        found = {}
        for path in sorted(UNIT.glob("*.py")):
            lines = offending_lines(path.read_text(encoding="utf-8"))
            if lines:
                found[path.name] = lines
        self.assertEqual(found, {}, "build these environments with child_env() from tests/lib/child_env.py (#833)")

    def test_the_check_finds_a_built_environment_however_it_is_reached(self):
        flagged = {
            "a literal": 'subprocess.run([sys.executable, "-I", "-c", code], env={"PATH": "/usr/bin"})',
            "one value read from the parent": 'subprocess.run([sys.executable], env={"PATH": os.environ["PATH"]})',
            "a local name": 'env = {"PATH": empty}\nsubprocess.run([sys.executable, "-c", c], env=env)',
            "spreads of built ones": (
                'env = {"PATH": p}\ndef run(**extra):\n    subprocess.run([sys.executable], env={**env, **extra})'
            ),
            "a command in a name": 'command = [sys.executable, "-I", w]\nsubprocess.run(command, env={"HOME": h})',
            "a module constant": 'PYTHON = sys.executable\ndef t():\n    subprocess.Popen([PYTHON], env={"A": "1"})',
            "dict() without the parent": 'subprocess.run([sys.executable], env=dict(PATH="/bin"))',
            "an attribute of the test": (
                "class T:\n    def setUp(self):\n        self.env = {'PATH': '/bin'}\n"
                "    def test(self):\n        subprocess.run([sys.executable], env=self.env)"
            ),
            "a name from the enclosing function": (
                "def test():\n    env = {'PATH': '/bin'}\n    def write():\n"
                "        return subprocess.run([sys.executable, w], env=env)\n    write()"
            ),
            "a loop over literal ones": (
                'for env in ({"PATH": "/bin"}, {"PATH": "/usr/bin"}):\n    subprocess.run([sys.executable], env=env)'
            ),
            "an attribute of the test class": (
                "class T:\n    env = {'PATH': '/bin'}\n"
                "    def test(self):\n        subprocess.run([sys.executable], env=self.env)"
            ),
        }
        for case, source in flagged.items():
            with self.subTest(case):
                self.assertNotEqual(offending_lines(source), [], source)

    def test_the_check_passes_the_helper_the_parent_and_other_commands(self):
        passing = {
            "the helper": 'subprocess.run([sys.executable], env=child_env({"PATH": "/bin"}))',
            "the helper through a name": 'env = child_env({"PATH": p})\nsubprocess.run([sys.executable], env={**env, "A": "1"})',
            "the parent spread": 'subprocess.run([sys.executable], env={**os.environ, "A": "1"})',
            "dict() of the parent": 'subprocess.run([sys.executable], env=dict(os.environ, A="1"))',
            "a copy of the parent": "subprocess.run([sys.executable], env=os.environ.copy())",
            "no env": "subprocess.run([sys.executable, '-c', 'pass'])",
            "a parameter": "def run(env):\n    subprocess.run([sys.executable], env=env)",
            "a spread of the parent's": "def run(**extra):\n    subprocess.run([sys.executable], env={**os.environ, **extra})",
            "not this Python": 'subprocess.run(["git", "status"], env={"PATH": "/usr/bin"})',
            "a bare copy()": "from copy import copy\nsubprocess.run([sys.executable], env=copy(os.environ))",
        }
        for case, source in passing.items():
            with self.subTest(case):
                self.assertEqual(offending_lines(source), [], source)


if __name__ == "__main__":
    unittest.main()
