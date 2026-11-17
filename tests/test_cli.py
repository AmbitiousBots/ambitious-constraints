from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ambitious_constraints.domain.model import digest_of
from tests.support import Cli, fixture

MODEL = fixture("two-offers.json")
DIGEST = digest_of(MODEL)


def commit(cli: Cli, model: object = MODEL, *, model_id: str = "offers", base: int = 0, key: str = "k1") -> dict[str, object]:
    return cli.call(
        "model commit",
        {"model_id": model_id, "base_version": base, "digest": digest_of(model), "model": model, "idem_key": key, "actor": "tester"},
    )


class WriteRules(unittest.TestCase):
    def setUp(self) -> None:
        self.cli = Cli()
        self.addCleanup(self.cli.close)
        self.cli.data("selfcheck")

    def test_propose_stores_nothing_and_returns_what_commit_needs(self) -> None:
        proposed = self.cli.data("model propose", {"model_id": "offers", "model": MODEL})
        self.assertEqual((proposed["digest"], proposed["base_version"], proposed["valid"], proposed["stored"]), (DIGEST, 0, True, False))
        self.assertEqual(self.cli.data("model list")["models"], [])
        self.assertEqual(self.cli.codes("model get", {"model_id": "offers"}), ["E_NOT_FOUND"])

    def test_commit_clone_history_and_the_refusals(self) -> None:
        first = commit(self.cli)
        self.assertEqual(first["data"], {"model_id": "offers", "version": 1, "digest": DIGEST, "replayed": False})
        self.assertEqual(commit(self.cli)["data"], {"model_id": "offers", "version": 1, "digest": DIGEST, "replayed": True})
        changed = {**MODEL, "description": "changed"}
        self.assertEqual(self.cli.codes("model commit", {"model_id": "offers", "base_version": 1, "digest": DIGEST, "model": changed, "idem_key": "k1", "actor": "tester"}), ["E_IDEM_CONFLICT"])
        stale = commit(self.cli, changed, base=0, key="k2")
        self.assertEqual([entry["code"] for entry in stale["errors"]], ["E_STALE"])
        self.assertEqual(stale["data"], {"model_id": "offers", "current_version": 1, "base_version": 0})
        wrong = self.cli.call("model commit", {"model_id": "offers", "base_version": 1, "digest": DIGEST, "model": changed, "idem_key": "k3", "actor": "tester"})
        self.assertEqual([entry["code"] for entry in wrong["errors"]], ["E_DIGEST"])
        proposed = self.cli.data("model propose", {"model_id": "offers", "model": changed})
        self.assertEqual(proposed["base_version"], 1)
        self.assertFalse(proposed["diff"]["unchanged"])
        second = commit(self.cli, changed, base=1, key="k4")
        self.assertEqual(second["data"]["version"], 2)
        cloned = self.cli.data("model clone", {"model_id": "offers", "version": 1, "new_id": "offers-copy", "idem_key": "k5", "actor": "tester"})
        self.assertEqual(cloned, {"model_id": "offers-copy", "version": 1, "digest": DIGEST, "forked_from": {"model_id": "offers", "version": 1}, "replayed": False})
        self.assertEqual(self.cli.codes("model clone", {"model_id": "offers", "new_id": "offers-copy", "idem_key": "k6", "actor": "tester"}), ["E_EXISTS"])
        self.assertEqual(self.cli.codes("model clone", {"model_id": "missing", "new_id": "other", "idem_key": "k7", "actor": "tester"}), ["E_NOT_FOUND"])
        source = self.cli.data("model get", {"model_id": "offers"})
        self.assertEqual((source["version"], source["latest_version"], source["forked_from"]), (2, 2, None))
        self.assertEqual(self.cli.data("model get", {"model_id": "offers", "version": 1})["model"], MODEL)
        copy = self.cli.data("model get", {"model_id": "offers-copy"})
        self.assertEqual((copy["model"], copy["forked_from"]), (MODEL, {"model_id": "offers", "version": 1}))
        events = self.cli.data("model history", {"model_id": "offers"})["events"]
        self.assertEqual([(event["kind"], event["version"]) for event in events], [("committed", 1), ("committed", 2)])
        self.assertEqual(self.cli.data("model history", {"model_id": "offers-copy"})["events"][0]["forked_from"], {"model_id": "offers", "version": 1})
        self.assertEqual([entry["model_id"] for entry in self.cli.data("model list")["models"]], ["offers", "offers-copy"])

    def test_a_model_with_problems_is_not_stored(self) -> None:
        broken = {**MODEL, "objective": {"sense": "max", "terms": [{"coef": 1, "var": "nowhere"}]}}
        refused = commit(self.cli, broken)
        self.assertEqual([entry["code"] for entry in refused["errors"]], ["E_MODEL"])
        self.assertEqual(refused["data"]["problems"][0]["code"], "UNKNOWN_VARIABLE")
        self.assertEqual(self.cli.data("model list")["models"], [])
        report = self.cli.data("model validate", {"model": broken})
        self.assertFalse(report["valid"])
        shape = self.cli.data("model validate", {"model": {**MODEL, "params": [{"name": "hours_available", "value": 20.5}]}})
        self.assertEqual((shape["valid"], shape["problems"][0]["code"]), (False, "SCHEMA"))
        self.assertEqual(self.cli.codes("model commit", {"model_id": "Bad Id", "base_version": 0, "digest": DIGEST, "model": MODEL, "idem_key": "k", "actor": "t"}), ["E_INPUT_SCHEMA"])
        self.assertEqual(self.cli.codes("solve", {"model": {**MODEL, "schema": "constraint-model.v2"}}), ["E_INPUT_SCHEMA"])

    def test_history_cannot_be_rewritten(self) -> None:
        commit(self.cli)
        db = sqlite3.connect(self.cli.db)
        self.addCleanup(db.close)
        for statement in (
            "UPDATE model_events SET actor = 'x'",
            "DELETE FROM model_events",
            "UPDATE model_versions SET doc = '{}'",
            "DELETE FROM model_versions",
        ):
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(statement)


class Analysis(unittest.TestCase):
    cli: Cli

    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = Cli()
        cls.addClassCleanup(cls.cli.close)
        commit(cls.cli)

    def test_solve_by_id_by_document_and_by_scenario(self) -> None:
        stored = self.cli.data("solve", {"model_id": "offers"})["solution"]
        inline = self.cli.data("solve", {"model": MODEL})["solution"]
        self.assertEqual(stored["status"], "infeasible")
        self.assertEqual(stored["model"], {"id": "offers", "name": "two-offers", "version": 1, "digest": DIGEST})
        self.assertEqual(inline["model"], {"name": "two-offers", "digest": DIGEST})
        more = self.cli.data("solve", {"model_id": "offers", "scenario": "more_hours"})["solution"]
        self.assertEqual((more["status"], more["objective"], more["bound"]), ("optimal", 2700, 2700))
        self.assertEqual(more["values"], {"hours": 30, "offer_basic": False, "offer_full": True, "tier": "full"})
        self.assertEqual(more["checked"], {"violations": []})
        self.assertEqual(more["rests_on_assumptions"], ["hours_fit"])
        self.assertEqual((more["solver"]["name"], more["solver"]["version"], more["solver"]["workers"]), ("cp-sat", "9.15.6755", 1))
        wish = self.cli.data("solve", {"model_id": "offers", "scenario": "full_is_a_wish"})["solution"]
        self.assertEqual((wish["objective"], wish["soft_violated"], wish["values"]["tier"]), (400, [{"id": "want_full", "weight": 500}], "basic"))
        self.assertEqual(self.cli.codes("solve", {"model_id": "offers", "scenario": "nope"}), ["E_NOT_FOUND"])
        self.assertEqual(self.cli.codes("solve", {"model_id": "offers", "model": MODEL}), ["E_INPUT_SCHEMA"])
        self.assertEqual(self.cli.codes("solve", {"model_id": "offers", "limits": {"deterministic_time": 0}}), ["E_INPUT_SCHEMA"])

    def test_explain_names_the_smallest_conflict_and_what_to_give_up(self) -> None:
        found = self.cli.data("explain", {"model_id": "offers"})
        self.assertEqual(found["status"], "infeasible")
        self.assertEqual([entry["ids"] for entry in found["mus"]], [["full_needs_hours", "hours_fit", "want_full"]])
        self.assertEqual([entry["ids"] for entry in found["mcs"]], [["want_full"]])
        self.assertEqual(found["rests_on_assumptions"], ["hours_fit"])
        members = {member["id"]: member for member in found["mus"][0]["members"]}
        self.assertEqual((members["hours_fit"]["confidence"], members["hours_fit"]["lever"]), ("assumption", False))
        self.assertEqual((members["full_needs_hours"]["confidence"], members["full_needs_hours"]["rests_on_assumption"]), ("sourced", False))
        self.assertEqual((members["want_full"]["lever"], members["want_full"]["label"]), (True, "Sell the full offer"))
        calm = self.cli.data("explain", {"model_id": "offers", "scenario": "more_hours"})
        self.assertEqual((calm["status"], calm["mus"], calm["mcs"]), ("feasible", [], []))

    def test_whatif_puts_scenarios_side_by_side(self) -> None:
        inline = {"name": "half_time", "overrides": {"params": {"hours_available": 10}, "disable": ["want_full"]}}
        compared = self.cli.data("whatif", {"model_id": "offers", "scenarios": ["more_hours", "full_is_a_wish", inline]})
        self.assertEqual(compared["scenarios"], [None, "more_hours", "full_is_a_wish", "half_time"])
        self.assertEqual([result["status"] for result in compared["results"]], ["infeasible", "optimal", "optimal", "optimal"])
        self.assertEqual([result["objective"] for result in compared["results"]], [None, 2700, 400, 900])
        self.assertEqual(compared["differences"]["tier"], [None, "full", "basic", "basic"])
        self.assertEqual(compared["differences"]["hours"], [None, 30, 10, 10])

    def test_sweep_finds_where_feasibility_flips(self) -> None:
        swept = self.cli.data("sweep", {"model_id": "offers", "param": "hours_available", "grid": [20, 25, 29, 30, 35]})
        self.assertEqual([point["status"] for point in swept["points"]], ["infeasible", "infeasible", "infeasible", "optimal", "optimal"])
        self.assertEqual(swept["flips"], [{"from": 29, "to": 30, "status_from": "infeasible", "status_to": "optimal"}])
        self.assertEqual((swept["base_value"], swept["rests_on_assumptions"]), (20, ["hours_fit"]))
        self.assertEqual(self.cli.codes("sweep", {"model_id": "offers", "param": "nope", "grid": [1]}), ["E_NOT_FOUND"])
        self.assertEqual(self.cli.codes("sweep", {"model_id": "offers", "param": "hours_available", "grid": [1.5]}), ["E_INPUT_SCHEMA"])

    def test_same_input_and_seed_print_the_same_bytes_on_another_day(self) -> None:
        for command, payload in (
            ("solve", {"model_id": "offers", "scenario": "more_hours"}),
            ("explain", {"model_id": "offers"}),
            ("whatif", {"model_id": "offers", "scenarios": ["more_hours"]}),
            ("sweep", {"model_id": "offers", "param": "hours_available", "grid": [20, 30]}),
        ):
            first = self.cli.raw(command, payload, seed=11).stdout
            self.assertEqual(first, self.cli.raw(command, payload, seed=11).stdout)
            other_day = json.loads(self.cli.raw(command, payload, seed=11, now="2031-07-09T12:34:56Z").stdout)
            self.assertEqual(json.loads(first)["data"], other_day["data"])

    def test_runs_are_recorded_once_and_read_back(self) -> None:
        envelope = self.cli.call("solve", {"model_id": "offers", "scenario": "more_hours"})
        request = {"envelope": envelope, "idem_key": "run-1", "actor": "tester", "note": "before the review"}
        recorded = self.cli.data("run record", request, now="2026-02-03T04:05:06Z")
        self.assertEqual((recorded["recorded"], recorded["replayed"], recorded["at"]), (True, False, "2026-02-03T04:05:06.000Z"))
        again = self.cli.data("run record", request, now="2027-01-01T00:00:00Z")
        self.assertEqual((again["run_id"], again["replayed"], again["at"]), (recorded["run_id"], True, "2026-02-03T04:05:06.000Z"))
        other_key = self.cli.data("run record", {**request, "idem_key": "run-2"})
        self.assertEqual((other_key["run_id"], other_key["recorded"]), (recorded["run_id"], False))
        read = self.cli.data("run get", {"run_id": recorded["run_id"]})
        self.assertEqual((read["envelope"], read["command"], read["model_id"], read["model_version"], read["note"]), (envelope, "solve", "offers", 1, "before the review"))
        self.assertEqual([entry["run_id"] for entry in self.cli.data("run list", {"model_id": "offers"})["runs"]], [recorded["run_id"]])
        self.assertEqual(self.cli.data("run list", {"model_id": "other"})["runs"], [])
        failed = self.cli.call("solve", {"model_id": "missing"})
        self.assertEqual(self.cli.codes("run record", {"envelope": failed, "idem_key": "run-3", "actor": "tester"}), ["E_INPUT_SCHEMA"])
        self.assertEqual(self.cli.codes("run get", {"run_id": "run-none"}), ["E_NOT_FOUND"])


class WithoutTheRuntime(unittest.TestCase):
    def test_everything_but_solving_works_and_solving_says_how_to_install_it(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            cli = Cli(Path(empty))
            self.addCleanup(cli.close)
            check = cli.data("selfcheck")
            self.assertEqual((check["pinnedRuntime"]["state"], check["problems"], len(check["warnings"])), ("missing", [], 1))
            self.assertIn("commands", cli.data("commands"))
            self.assertTrue(cli.data("model validate", {"model": MODEL})["valid"])
            self.assertTrue(cli.data("model propose", {"model": MODEL})["valid"])
            self.assertEqual(commit(cli)["data"]["version"], 1)
            cli.data("model clone", {"model_id": "offers", "new_id": "copy", "idem_key": "c", "actor": "tester"})
            self.assertEqual(len(cli.data("model history", {"model_id": "offers"})["events"]), 1)
            for command, payload in (
                ("solve", {"model_id": "offers"}),
                ("explain", {"model_id": "offers"}),
                ("whatif", {"model_id": "offers", "scenarios": ["more_hours"]}),
                ("sweep", {"model_id": "offers", "param": "hours_available", "grid": [1]}),
            ):
                refused = cli.raw(command, payload)
                answer = json.loads(refused.stdout)
                self.assertEqual(([entry["code"] for entry in answer["errors"]], refused.returncode), (["E_RUNTIME"], 1))
                self.assertIn("--runtime", answer["errors"][0]["hint"])
                self.assertEqual(answer["data"]["pinnedRuntime"]["state"], "missing")


class Limits(unittest.TestCase):
    def test_a_model_over_the_size_limit_is_refused_with_a_clear_problem(self) -> None:
        cli = Cli()
        self.addCleanup(cli.close)
        huge = {**MODEL, "variables": [{"name": f"x{index}", "type": "bool"} for index in range(20_001)], "constraints": [], "objective": None, "evidence": [], "scenarios": []}
        report = cli.data("model validate", {"model": huge})
        self.assertEqual((report["valid"], report["problems"][0]["code"]), (False, "TOO_LARGE"))


if __name__ == "__main__":
    unittest.main()
