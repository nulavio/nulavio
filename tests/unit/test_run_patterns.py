"""tests/run.py runs every pattern given after the suite name, not only the first (#498)."""

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_runner():
    spec = importlib.util.spec_from_file_location("nulavio_tests_run", ROOT / "tests" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunPatternsTest(unittest.TestCase):
    def discovered(self, argv):
        runner = load_runner()
        seen = []

        def discover(_loader, start_dir, pattern, top_level_dir=None):
            seen.append((Path(start_dir).name, pattern))
            return unittest.TestSuite()

        ok = unittest.TestResult()
        with (
            mock.patch.object(unittest.TestLoader, "discover", discover),
            mock.patch.object(unittest.TextTestRunner, "run", return_value=ok),
        ):
            self.assertEqual(runner.main(argv), 0)
        return seen

    def test_every_pattern_after_the_suite_is_discovered(self):
        self.assertEqual(
            self.discovered(["run.py", "unit", "test_a.py", "test_b.py"]),
            [("unit", "test_a.py"), ("unit", "test_b.py")],
        )

    def test_no_pattern_means_every_test_file(self):
        self.assertEqual(self.discovered(["run.py", "unit"]), [("unit", "test*.py")])


if __name__ == "__main__":
    unittest.main()
