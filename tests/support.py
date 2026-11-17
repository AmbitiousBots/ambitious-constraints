from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from ambitious_kit.runtime import activate, lock_sha256, pinned_runtime

from ambitious_constraints.cli.main import RUNTIME_LOCK
from ambitious_constraints.domain.analysis import Outcome, Run
from ambitious_constraints.domain.explain import Oracle
from ambitious_constraints.domain.model import Compiled

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("AMBITIOUS_HOME") or ROOT / ".build" / "home")
BINARY = ROOT / "dist" / "ambitious-constraints.pyz"
NOW = "2026-01-01T00:00:00Z"


class SolverEngine:
    def __init__(self) -> None:
        activate(pinned_runtime({"AMBITIOUS_HOME": str(HOME)}, "constraints", RUNTIME_LOCK))
        from ambitious_constraints.solver import cpsat

        self.cpsat = cpsat

    def version(self) -> str:
        return self.cpsat.solver_version()

    def lock_sha256(self) -> str:
        return lock_sha256(RUNTIME_LOCK)

    def solve(self, model: Compiled, seed: int, deterministic_time: int) -> Outcome:
        return self.cpsat.solve(model, seed, deterministic_time)

    def oracle(self, model: Compiled, seed: int, deterministic_time: int) -> Oracle:
        return self.cpsat.ConflictOracle(model, seed, deterministic_time)


def run(deterministic_time: int = 60, seed: int = 7) -> Run:
    return Run(SolverEngine(), seed, deterministic_time)


class Cli:
    def __init__(self, home: Path | None = None) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.db = str(Path(self.directory.name) / "constraints.sqlite")
        self.home = HOME if home is None else home

    def close(self) -> None:
        self.directory.cleanup()

    def raw(self, command: str, payload: object | None = None, *, seed: int = 7, now: str = NOW) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(BINARY), *command.split(" "), "--db", self.db, "--now", now, "--seed", str(seed)],
            input="" if payload is None else json.dumps(payload),
            capture_output=True,
            text=True,
            env={**os.environ, "AMBITIOUS_HOME": str(self.home)},
            check=False,
        )

    def call(self, command: str, payload: object | None = None, *, seed: int = 7, now: str = NOW) -> dict[str, object]:
        done = self.raw(command, payload, seed=seed, now=now)
        parsed: dict[str, object] = json.loads(done.stdout)
        expected = 0 if parsed["ok"] else 1
        if done.returncode != expected and not (done.returncode == 2 and not parsed["ok"]):
            raise AssertionError(f"{command} exited {done.returncode}: {done.stdout}")
        return parsed

    def data(self, command: str, payload: object | None = None, *, seed: int = 7, now: str = NOW) -> Mapping[str, object]:
        parsed = self.call(command, payload, seed=seed, now=now)
        if parsed["ok"] is not True:
            raise AssertionError(f"{command} failed: {parsed['errors']}")
        data = parsed["data"]
        assert isinstance(data, dict)
        return data

    def codes(self, command: str, payload: object | None = None) -> list[str]:
        errors = self.call(command, payload)["errors"]
        assert isinstance(errors, list)
        return [str(entry["code"]) for entry in errors]


def fixture(name: str) -> dict[str, object]:
    parsed: dict[str, object] = json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))
    return parsed
