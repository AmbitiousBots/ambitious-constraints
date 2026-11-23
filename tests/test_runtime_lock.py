from __future__ import annotations

import subprocess
import unittest
from importlib.metadata import distributions
from pathlib import Path

from ambitious_kit.runtime import pinned_runtime

from ambitious_constraints.cli.main import RUNTIME_LOCK
from tests.support import HOME


class RuntimeLock(unittest.TestCase):
    def test_protobuf_hold(self) -> None:
        runtime = pinned_runtime({"AMBITIOUS_HOME": str(HOME)}, "constraints", RUNTIME_LOCK)
        self.assertEqual(runtime.state, "ready", runtime.problem)
        (ortools,) = distributions(name="ortools", path=[runtime.site_packages])
        requirements = [req for req in ortools.requires or [] if req.lower().startswith("protobuf")]
        bounds = {
            bound.strip()
            for req in requirements
            if ";" not in req
            for bound in req.lower().removeprefix("protobuf").split(",")
        }
        self.assertIn(
            "<6.34",
            bounds,
            f"OR-Tools {ortools.version} declares {requirements}. Refresh protobuf in runtime.txt "
            "to the newest version the wheel allows and update the cap check.",
        )
        check = subprocess.run(
            [Path(runtime.path, "bin", "python"), "-I", "-m", "pip", "check"], capture_output=True, text=True
        )
        self.assertEqual(
            check.returncode,
            0,
            f"Regenerate runtime.txt to satisfy the wheel requirements.\n{check.stdout}{check.stderr}",
        )
