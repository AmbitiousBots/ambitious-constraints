from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HOME = Path(os.environ["AMBITIOUS_HOME"])
NOW = ["--now", "2026-01-01T00:00:00Z", "--seed", "7"]
MODEL = json.loads((ROOT / "tests" / "fixtures" / "two-offers.json").read_text(encoding="utf-8"))


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def module(command: str, payload: object | None = None, *, expect: str | None = None) -> dict[str, object]:
    done = subprocess.run(
        [sys.executable, str(HOME / "bin" / "ambitious-constraints"), *command.split(" "), *NOW],
        input="" if payload is None else json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    answer = json.loads(done.stdout)
    codes = [entry["code"] for entry in answer["errors"]]
    if (expect is None and not answer["ok"]) or (expect is not None and codes != [expect]):
        fail(f"{command} answered {codes or 'ok'}: {done.stdout[:400]}")
    data: dict[str, object] = answer["data"]
    return answer if command == "solve" and expect is None else data


def main() -> None:
    if any(HOME.iterdir()):
        fail(f"{HOME} is not empty")
    installed = subprocess.run(["node", str(ROOT / "scripts" / "runtime.mjs"), str(HOME)], cwd=ROOT, check=False)
    if installed.returncode != 0:
        fail("the kit installer could not install the binary and its runtime")
    check = module("selfcheck")
    if check["problems"] != [] or check["warnings"] != [] or check["pinnedRuntime"]["state"] != "ready":
        fail(f"selfcheck is not clean: {check}")
    proposed = module("model propose", {"model_id": "offers", "model": MODEL})
    if proposed["valid"] is not True or proposed["base_version"] != 0:
        fail(f"propose: {proposed}")
    if module("model list")["models"] != []:
        fail("propose stored something")
    commit = {
        "model_id": "offers",
        "base_version": proposed["base_version"],
        "digest": proposed["digest"],
        "model": MODEL,
        "idem_key": "story-commit",
        "actor": "verify",
    }
    if module("model commit", commit)["version"] != 1:
        fail("commit did not store version 1")
    module("model commit", {**commit, "idem_key": "story-commit-again"}, expect="E_STALE")
    conflict = module("explain", {"model_id": "offers"})
    if conflict["status"] != "infeasible" or [entry["ids"] for entry in conflict["mcs"]] != [["want_full"]]:
        fail(f"explain: {conflict}")
    envelope = module("solve", {"model_id": "offers", "scenario": "more_hours"})
    solution = envelope["data"]["solution"]
    if solution["status"] != "optimal" or solution["objective"] != 2700 or solution["checked"] != {"violations": []}:
        fail(f"solve: {solution}")
    swept = module("sweep", {"model_id": "offers", "param": "hours_available", "grid": [20, 29, 30]})
    if swept["flips"] != [{"from": 29, "to": 30, "status_from": "infeasible", "status_to": "optimal"}]:
        fail(f"sweep: {swept}")
    compared = module("whatif", {"model_id": "offers", "scenarios": ["more_hours", "full_is_a_wish"]})
    if [result["objective"] for result in compared["results"]] != [None, 2700, 400]:
        fail(f"whatif: {compared}")
    recorded = module("run record", {"envelope": envelope, "idem_key": "story-run", "actor": "verify"})
    if module("run get", {"run_id": recorded["run_id"]})["envelope"] != envelope:
        fail("the recorded run does not read back as it was stored")
    sys.stdout.write(
        f"installed with runtime, selfcheck clean, committed v1, stale commit refused, conflict explained, "
        f"solved to {solution['objective']} with CP-SAT {solution['solver']['version']}, "
        f"run {recorded['run_id']} recorded\n"
    )


if __name__ == "__main__":
    main()
