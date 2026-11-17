from __future__ import annotations

import unittest

from ambitious_constraints.domain.analysis import Run, explain, prepare, solution
from tests.support import fixture, run

FIXTURE = fixture("planning-regression.json")
MODEL = FIXTURE["model"]
EXPECTED = FIXTURE["expected"]
REFERENCE = {"name": "planning-regression", "digest": "0" * 64}


class PlanningRegression(unittest.TestCase):
    engine: Run

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = run()

    def test_every_scenario_has_the_recorded_status_and_optimum(self) -> None:
        assert isinstance(MODEL, dict) and isinstance(EXPECTED, dict)
        self.assertEqual(len(EXPECTED), 11)
        for scenario, expected in EXPECTED.items():
            with self.subTest(scenario=scenario):
                solved = solution(MODEL, REFERENCE, scenario, self.engine)
                self.assertEqual(solved["status"], expected["status"])
                self.assertEqual(solved["objective"], expected["objective"])
                self.assertEqual(solved["checked"], {"violations": []})
                if expected["status"] == "optimal":
                    violated = solved["soft_violated"]
                    assert isinstance(violated, list)
                    self.assertEqual(sorted(entry["id"] for entry in violated), expected["soft_violated"])

    def test_infeasible_scenarios_have_the_recorded_correction_sets_and_every_recorded_conflict_is_minimal(
        self,
    ) -> None:
        assert isinstance(MODEL, dict) and isinstance(EXPECTED, dict)
        checked = 0
        for scenario, expected in EXPECTED.items():
            if expected["status"] != "infeasible":
                continue
            with self.subTest(scenario=scenario):
                found = explain(MODEL, REFERENCE, scenario, self.engine, 40, 6)
                self.assertEqual(found["status"], "infeasible")
                self.assertTrue(found["complete"])
                mcs = found["mcs"]
                assert isinstance(mcs, list)
                self.assertEqual(sorted(entry["ids"] for entry in mcs), expected["mcs"])
                oracle = self.engine.engine.oracle(prepare(MODEL, scenario)[1], 7, 60)
                mus = found["mus"]
                assert isinstance(mus, list)
                for conflict in [*expected["mus"], *(entry["ids"] for entry in mus)]:
                    members = frozenset(conflict)
                    self.assertIsNotNone(oracle.core(members), f"{conflict} must be infeasible")
                    for member in members:
                        self.assertIsNone(
                            oracle.core(members - {member}), f"{conflict} without {member} must be feasible"
                        )
                    checked += 1
        self.assertGreaterEqual(checked, 38)


if __name__ == "__main__":
    unittest.main()
