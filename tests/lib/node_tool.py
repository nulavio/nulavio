"""The one gate for the unit test classes that drive a Shell module under Node (#788).

Where `node` is not on PATH such a class is skipped, as a missing optional tool's tests are. With
NULAVIO_REQUIRE_NODE=1, which CI's unit job sets, it fails instead: a runner image or container without Node
must not turn these behavioural tests into silent skips (I12). tests/unit/test_node_tool.py checks that every
class that runs `node` goes through `requires_node`.
"""

from __future__ import annotations

import os
import shutil
import unittest

KNOB = "NULAVIO_REQUIRE_NODE"


def requires_node(cls: type[unittest.TestCase]) -> type[unittest.TestCase]:
    """Class decorator: run the class where `node` is on PATH, else skip it, or fail it under NULAVIO_REQUIRE_NODE=1."""
    if shutil.which("node"):
        return cls
    if os.environ.get(KNOB) == "1":

        def refuse(klass) -> None:
            raise RuntimeError(f"{KNOB}=1 but node is not on PATH: {klass.__qualname__} cannot run")

        cls.setUpClass = classmethod(refuse)  # an error for the class, never a skip
        return cls
    return unittest.skip(f"node is not installed (CI sets {KNOB}=1)")(cls)
