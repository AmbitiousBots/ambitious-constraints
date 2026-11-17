from __future__ import annotations

import hashlib
import json
import unittest
from importlib.resources import files

import build_model
from ambitious_kit.domain.json_schema import describe_schema_problems, schema_problems

from ambitious_constraints.domain.analysis import solution
from tests.support import fixture, run
from tests.test_intervals import schedule_model

SCHEMAS = files("ambitious_constraints") / "schemas"
PINNED = {
    "constraint-model.v1.json": "08af8836f66e512bacaf27d404a59f1ac78d257ae51183f36af9a6766f33b7c9",
    "constraint-solution.v1.json": "3d4deef41e09c17d596cd3016375a5bef0e5553e26cbf81824ee8c659da75417",
}


def schema(name: str) -> object:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


class InterchangeSchemas(unittest.TestCase):
    def test_the_copies_are_the_files_the_kit_publishes(self) -> None:
        for name, expected in PINNED.items():
            self.assertEqual(hashlib.sha256((SCHEMAS / name).read_bytes()).hexdigest(), expected, name)

    def test_every_model_this_repository_ships_matches_the_model_schema(self) -> None:
        models = [
            fixture("two-offers.json"),
            fixture("planning-regression.json")["model"],
            build_model.build(build_model.Case("lognorm_250", 1000, 22.5, 4.0, "profit")),
            build_model.build(
                build_model.Case("linear_tools", 300, 15, 2.0, "revenue", floor_objective=10, price_direction="min")
            ),
            schedule_model(5, 2, 60, 1, hinted=True)[0],
        ]
        for model in models:
            self.assertEqual(describe_schema_problems(schema_problems(schema("constraint-model.v1.json"), model)), "")

    def test_every_solution_matches_the_solution_schema(self) -> None:
        engine = run()
        reference = {"name": "two-offers", "digest": "0" * 64}
        for scenario in (None, "more_hours", "full_is_a_wish"):
            solved = solution(fixture("two-offers.json"), reference, scenario, engine)
            self.assertEqual(
                describe_schema_problems(schema_problems(schema("constraint-solution.v1.json"), solved)), ""
            )
            self.assertEqual(solved["schema"], "constraint-solution.v1")


if __name__ == "__main__":
    unittest.main()
