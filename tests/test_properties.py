from __future__ import annotations

import itertools
import random
import unittest
from collections.abc import Iterator, Mapping

from ambitious_constraints.domain.analysis import Run, explain, solution
from ambitious_constraints.domain.check import check
from ambitious_constraints.domain.explain import enumerate_conflicts
from ambitious_constraints.domain.model import Compiled, compile_model
from tests.support import run

REFERENCE = {"name": "random", "digest": "0" * 64}
CATEGORIES = ("desire", "goal", "policy", "fact", "assumption")


def random_model(rng: random.Random, *, tight: bool) -> dict[str, object]:
    bools = [f"b{index}" for index in range(rng.randint(4, 8))]
    ints = [f"i{index}" for index in range(rng.randint(1, 2))]
    variables: list[dict[str, object]] = [{"name": name, "type": "bool"} for name in bools]
    variables += [{"name": name, "type": "int", "domain": {"lo": 0, "hi": rng.randint(2, 4)}} for name in ints]
    variables.append({"name": "mode", "type": "enum", "domain": {"values": ["a", "b", "c"]}})
    literals = bools + [f"!{name}" for name in bools] + ["mode=a", "mode=b", "!mode=c"]
    constraints: list[dict[str, object]] = []
    for index in range(rng.randint(5, 10) + (4 if tight else 0)):
        kind = rng.choice(("linear", "linear", "implication", "at_most_one", "exactly_one", "fix"))
        args: dict[str, object]
        if kind == "linear":
            names = rng.sample(bools + ints + ["mode=a"], rng.randint(1, 4))
            args = {
                "terms": [[rng.randint(-3, 4), name] for name in names],
                "op": rng.choice(("<=", ">=", "==", "!=")),
                "rhs": rng.randint(-2, 5),
            }
            if rng.random() < 0.3:
                args["if"] = [rng.choice(literals)]
        elif kind == "implication":
            args = {
                "if": rng.sample(literals, rng.randint(0, 2)),
                "then": rng.sample(literals, rng.randint(1, 2)),
                "all": rng.random() < 0.5,
            }
        elif kind == "fix":
            args = (
                {"lit": rng.choice(literals)}
                if rng.random() < 0.6
                else {"var": rng.choice(ints), "value": rng.randint(0, 3)}
            )
        else:
            args = {"lits": rng.sample(literals, rng.randint(2, 4))}
        strength = rng.choice(("hard", "hard", "hard", "structural", "soft"))
        constraints.append(
            {
                "id": f"c{index:02d}",
                "kind": kind,
                "args": args,
                "strength": strength,
                "weight": rng.randint(1, 9) if strength == "soft" else 0,
                "category": rng.choice(CATEGORIES),
                "negotiable": rng.random() < 0.8,
            }
        )
    terms = [{"coef": rng.randint(-5, 5), "var": name} for name in rng.sample(bools + ints, 3)]
    return {
        "schema": "constraint-model.v1",
        "name": "random",
        "variables": variables,
        "constraints": constraints,
        "objective": {"sense": rng.choice(("max", "min")), "terms": terms},
    }


def assignments(model: Compiled) -> Iterator[dict[str, int]]:
    names = [variable.name for variable in model.variables]
    domains = [[value for lo, hi in variable.ranges for value in range(lo, hi + 1)] for variable in model.variables]
    for values in itertools.product(*domains):
        yield dict(zip(names, values, strict=True))


class BruteOracle:
    def __init__(self, model: Compiled) -> None:
        self.model = model
        self.hard = frozenset(constraint.id for constraint in model.constraints if constraint.strength == "hard")
        self.space = list(assignments(model))

    def feasible(self, active: frozenset[str]) -> bool:
        return any(not check(self.model, values, self.hard - active).violations for values in self.space)

    def core(self, active: frozenset[str]) -> frozenset[str] | None:
        return None if self.feasible(active) else active & self.hard

    def best(self) -> int | None:
        scores = [
            checked.objective
            for values in self.space
            if not (checked := check(self.model, values)).violations and checked.objective is not None
        ]
        if not scores:
            return None
        objective = self.model.objective
        return max(scores) if objective is not None and objective.maximize else min(scores)


class Properties(unittest.TestCase):
    engine: Run

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = run()

    def test_solver_agrees_with_brute_force_on_status_and_optimum(self) -> None:
        rng = random.Random(20261117)
        outcomes = {"optimal": 0, "infeasible": 0}
        for case in range(120):
            raw = random_model(rng, tight=case % 3 == 0)
            brute = BruteOracle(compile_model(raw)[0])
            solved = solution(raw, REFERENCE, None, self.engine)
            with self.subTest(case=case):
                expected = brute.best()
                self.assertEqual(solved["status"], "infeasible" if expected is None else "optimal")
                self.assertEqual(solved["objective"], expected)
                self.assertEqual(solved["checked"], {"violations": []})
            outcomes[str(solved["status"])] += 1
        self.assertGreater(outcomes["optimal"], 20)
        self.assertGreater(outcomes["infeasible"], 20)

    def test_every_conflict_set_is_minimal_and_every_correction_set_restores_feasibility(self) -> None:
        rng = random.Random(42)
        explained = 0
        for case in range(120):
            raw = random_model(rng, tight=True)
            model = compile_model(raw)[0]
            brute = BruteOracle(model)
            found = explain(raw, REFERENCE, None, self.engine, 30, 6)
            with self.subTest(case=case):
                self.assertEqual(found["status"], "feasible" if brute.feasible(brute.hard) else "infeasible")
                mus, mcs = found["mus"], found["mcs"]
                assert isinstance(mus, list) and isinstance(mcs, list)
                for entry in mus:
                    members = frozenset(entry["ids"])
                    self.assertFalse(brute.feasible(members))
                    for member in members:
                        self.assertTrue(brute.feasible(members - {member}))
                for entry in mcs:
                    dropped = frozenset(entry["ids"])
                    self.assertTrue(dropped <= model.levers())
                    self.assertTrue(brute.feasible(brute.hard - dropped))
                    for member in dropped:
                        self.assertFalse(brute.feasible(brute.hard - (dropped - {member})))
                if found["status"] == "infeasible" and found["complete"]:
                    reference = enumerate_conflicts(brute, brute.hard, model.levers(), 30, 6)
                    self.assertEqual(sorted(entry["ids"] for entry in mcs), sorted(list(ids) for ids in reference.mcs))
                    explained += 1
        self.assertGreater(explained, 30)

    def test_checker_agrees_with_the_solver_on_random_assignments(self) -> None:
        rng = random.Random(7)
        accepted = refused = 0
        for case in range(60):
            raw = random_model(rng, tight=False)
            model = compile_model(raw)[0]
            listed = raw["constraints"]
            assert isinstance(listed, list)
            hard_only = [dict(entry, strength="structural") for entry in listed if entry["strength"] != "soft"]
            strict = compile_model({**raw, "constraints": hard_only, "objective": None})[0]
            for _ in range(5):
                values = {
                    variable.name: rng.choice([v for lo, hi in variable.ranges for v in range(lo, hi + 1)])
                    for variable in model.variables
                }
                pinned = [
                    {
                        "id": f"pin_{name}",
                        "kind": "linear",
                        "args": {"terms": [[1, name]], "op": "==", "rhs": value},
                        "strength": "structural",
                    }
                    for name, value in values.items()
                    if model.variable(name).type != "enum"
                ]
                pinned.append(
                    {
                        "id": "pin_mode",
                        "kind": "fix",
                        "args": {"lit": f"mode={'abc'[values['mode']]}"},
                        "strength": "structural",
                    }
                )
                fixed = {**raw, "constraints": hard_only + pinned, "objective": None}
                by_solver = solution(fixed, REFERENCE, None, self.engine)["status"] != "infeasible"
                by_checker = not check(strict, values).violations
                with self.subTest(case=case, values=values):
                    self.assertEqual(by_checker, by_solver)
                accepted += by_checker
                refused += not by_checker
        self.assertGreater(accepted, 10)
        self.assertGreater(refused, 10)

    def test_same_seed_gives_the_same_solution_and_explanation(self) -> None:
        rng = random.Random(3)
        for _ in range(10):
            raw: Mapping[str, object] = random_model(rng, tight=True)
            self.assertEqual(solution(raw, REFERENCE, None, self.engine), solution(raw, REFERENCE, None, self.engine))
            self.assertEqual(
                explain(raw, REFERENCE, None, self.engine, 30, 6), explain(raw, REFERENCE, None, self.engine, 30, 6)
            )


if __name__ == "__main__":
    unittest.main()
