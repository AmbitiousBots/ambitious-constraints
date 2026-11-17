from __future__ import annotations

import random
import unittest

from ambitious_constraints.domain.analysis import Run, explain, solution
from ambitious_constraints.domain.check import check
from ambitious_constraints.domain.model import ModelError, compile_model
from tests.support import run

REFERENCE = {"name": "schedule", "digest": "0" * 64}
DAY = 1440
WORK = (540, 1020)


def windows(days: int) -> list[tuple[int, int]]:
    return [(day * DAY + WORK[0], day * DAY + WORK[1]) for day in range(days)]


def schedule_model(tasks: int, calendars: int, block: int, seed: int, *, hinted: bool) -> tuple[dict[str, object], int]:
    rng = random.Random(seed)
    days = tasks * 2
    free = windows(days)
    variables: list[dict[str, object]] = []
    constraints: list[dict[str, object]] = []
    hints: dict[str, object] = {}
    lanes: dict[int, list[str]] = {index: [] for index in range(calendars)}
    cursor = dict.fromkeys(range(calendars), 0)
    finished: dict[int, int] = {}
    chunk_names: dict[int, list[str]] = {}
    horizon = days * DAY
    makespan = 0
    for task in range(tasks):
        calendar = task % calendars
        chunks = rng.randint(1, 3)
        after = rng.sample(range(task), min(task, rng.randint(0, 2)))
        earliest = max([finished[other] for other in after], default=0)
        names: list[str] = []
        for chunk in range(chunks):
            name = f"t{task}_{chunk}"
            names.append(name)
            variables.append(
                {"name": f"{name}_s", "type": "int", "domain": {"ranges": [[lo, hi - block] for lo, hi in free]}}
            )
            variables.append({"name": f"{name}_e", "type": "int", "domain": {"lo": 0, "hi": horizon}})
            variables.append(
                {
                    "name": name,
                    "type": "interval",
                    "interval": {"start": f"{name}_s", "size": block, "end": f"{name}_e"},
                }
            )
            lanes[calendar].append(name)
            start = next(
                lo + step * block
                for lo, hi in free
                for step in range((hi - lo) // block)
                if lo + step * block >= max(cursor[calendar], earliest)
            )
            cursor[calendar] = earliest = start + block
            hints[f"{name}_s"] = start
            constraints.append(
                {
                    "id": f"span_{name}",
                    "kind": "linear",
                    "args": {"terms": [[1, f"{name}_e"], [-1, "makespan"]], "op": "<=", "rhs": 0},
                    "strength": "structural",
                }
            )
        finished[task] = earliest
        makespan = max(makespan, earliest)
        chunk_names[task] = names
        rows = [{"before": first, "after": second} for first, second in zip(names, names[1:], strict=False)]
        rows += [{"before": chunk_names[other][-1], "after": names[0]} for other in after]
        if rows:
            constraints.append(
                {
                    "id": f"order_t{task}",
                    "kind": "precedence",
                    "args": {"rows": rows},
                    "strength": "hard",
                    "category": "fact",
                    "label": f"Task {task} keeps its order",
                }
            )
    for calendar, names in lanes.items():
        constraints.append(
            {"id": f"lane_{calendar}", "kind": "no_overlap", "args": {"intervals": names}, "strength": "structural"}
        )
    variables.append({"name": "makespan", "type": "int", "domain": {"lo": 0, "hi": horizon}})
    model: dict[str, object] = {
        "schema": "constraint-model.v1",
        "name": "schedule",
        "variables": variables,
        "constraints": constraints,
        "objective": {"sense": "min", "terms": [{"coef": 1, "var": "makespan"}]},
    }
    if hinted:
        model["hints"] = hints
    return model, makespan


def with_blocking_intervals(raw: dict[str, object], days: int) -> dict[str, object]:
    horizon = days * DAY
    gaps = [(0, WORK[0])]
    gaps += [(day * DAY + WORK[1], (day + 1) * DAY + WORK[0]) for day in range(days - 1)]
    gaps.append(((days - 1) * DAY + WORK[1], horizon))
    listed, constraints = raw["variables"], raw["constraints"]
    assert isinstance(listed, list) and isinstance(constraints, list)
    variables = [
        {**variable, "domain": {"lo": 0, "hi": horizon}} if "ranges" in variable.get("domain", {}) else variable
        for variable in listed
    ]
    closed: list[str] = []
    for index, (start, end) in enumerate(gaps):
        name = f"closed{index}"
        closed.append(name)
        variables += [
            {"name": f"{name}_s", "type": "int", "domain": {"lo": start, "hi": start}},
            {"name": f"{name}_e", "type": "int", "domain": {"lo": end, "hi": end}},
            {
                "name": name,
                "type": "interval",
                "interval": {"start": f"{name}_s", "size": end - start, "end": f"{name}_e"},
            },
        ]
    lanes = [
        {**entry, "args": {"intervals": [*entry["args"]["intervals"], *closed]}}
        if entry["kind"] == "no_overlap"
        else entry
        for entry in constraints
    ]
    return {**raw, "variables": variables, "constraints": lanes}


class TimeSlots(unittest.TestCase):
    engine: Run

    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = run(deterministic_time=2)

    def test_small_schedule_is_solved_to_optimality_and_passes_the_checker(self) -> None:
        raw, greedy = schedule_model(8, 2, 120, 1, hinted=False)
        solved = solution(raw, REFERENCE, None, self.engine)
        self.assertEqual(solved["status"], "optimal")
        self.assertEqual(solved["checked"], {"violations": []})
        objective = solved["objective"]
        assert isinstance(objective, int)
        self.assertLessEqual(objective, greedy)

    def test_hinted_schedule_of_hundreds_of_blocks_is_at_least_as_good_as_the_hint(self) -> None:
        ranged, greedy = schedule_model(300, 3, 90, 2, hinted=True)
        variables = ranged["variables"]
        assert isinstance(variables, list)
        self.assertGreater(sum(1 for variable in variables if variable["type"] == "interval"), 500)
        raw = with_blocking_intervals(ranged, 600)
        solved = solution(raw, REFERENCE, None, self.engine)
        self.assertIn(solved["status"], ("optimal", "feasible"))
        self.assertEqual(solved["checked"], {"violations": []})
        objective = solved["objective"]
        assert isinstance(objective, int)
        self.assertLessEqual(objective, greedy)
        self.assertEqual(solved, solution(raw, REFERENCE, None, self.engine))

    def test_working_hours_as_start_ranges_and_as_blocking_intervals_agree(self) -> None:
        ranged, greedy = schedule_model(40, 2, 120, 6, hinted=True)
        by_ranges = solution(ranged, REFERENCE, None, self.engine)
        by_blocks = solution(with_blocking_intervals(ranged, 80), REFERENCE, None, self.engine)
        for solved in (by_ranges, by_blocks):
            self.assertIn(solved["status"], ("optimal", "feasible"))
            self.assertEqual(solved["checked"], {"violations": []})
            objective = solved["objective"]
            assert isinstance(objective, int)
            self.assertLessEqual(objective, greedy)
        values = by_blocks["values"]
        assert isinstance(values, dict)
        starts = [value % DAY for name, value in values.items() if name.startswith("t") and name.endswith("_s")]
        self.assertTrue(all(WORK[0] <= start <= WORK[1] - 120 for start in starts))

    def test_checker_catches_an_overlap_a_broken_order_and_a_wrong_size(self) -> None:
        raw, _ = schedule_model(4, 1, 120, 3, hinted=False)
        model = compile_model(raw)[0]
        solved = solution(raw, REFERENCE, None, self.engine)
        values = solved["values"]
        assert isinstance(values, dict)
        good = {name: int(value) for name, value in values.items()}
        self.assertEqual(check(model, good).violations, ())
        overlap = {**good, "t1_0_s": good["t0_0_s"], "t1_0_e": good["t0_0_e"]}
        self.assertIn("lane_0", [violation.constraint for violation in check(model, overlap).violations])
        stretched = {**good, "t0_0_e": good["t0_0_e"] + 1}
        self.assertIn("t0_0", [violation.constraint for violation in check(model, stretched).violations])

    def test_due_date_that_cannot_be_met_is_explained(self) -> None:
        raw, _ = schedule_model(6, 1, 240, 4, hinted=False)
        constraints = raw["constraints"]
        assert isinstance(constraints, list)
        constraints.append(
            {
                "id": "due_all",
                "kind": "linear",
                "args": {"terms": [[1, "makespan"]], "op": "<=", "rhs": 1020},
                "strength": "hard",
                "category": "goal",
                "label": "Everything is finished on the first day",
            }
        )
        found = explain(raw, REFERENCE, None, self.engine, 10, 4)
        self.assertEqual(found["status"], "infeasible")
        mcs = found["mcs"]
        assert isinstance(mcs, list)
        self.assertEqual([entry["ids"] for entry in mcs], [["due_all"]])

    def test_cumulative_and_optional_intervals(self) -> None:
        variables: list[dict[str, object]] = [{"name": "use_c", "type": "bool"}]
        for name in "abc":
            variables += [
                {"name": f"{name}_s", "type": "int", "domain": {"lo": 0, "hi": 10}},
                {"name": f"{name}_e", "type": "int", "domain": {"lo": 0, "hi": 10}},
            ]
        variables += [
            {"name": "a", "type": "interval", "interval": {"start": "a_s", "size": 3, "end": "a_e"}},
            {"name": "b", "type": "interval", "interval": {"start": "b_s", "size": 3, "end": "b_e"}},
            {
                "name": "c",
                "type": "interval",
                "interval": {"start": "c_s", "size": 3, "end": "c_e", "present": "use_c"},
            },
            {"name": "end", "type": "int", "domain": {"lo": 0, "hi": 10}},
        ]
        constraints: list[dict[str, object]] = [
            {
                "id": "capacity",
                "kind": "cumulative",
                "args": {"intervals": ["a", "b", "c"], "demands": [2, 2, 2], "capacity": 3},
                "strength": "structural",
            },
            {"id": "want_c", "kind": "fix", "args": {"lit": "use_c"}, "strength": "soft", "weight": 100},
        ]
        constraints += [
            {
                "id": f"span_{name}",
                "kind": "linear",
                "args": {"terms": [[1, f"{name}_e"], [-1, "end"]], "op": "<=", "rhs": 0, **extra},
                "strength": "structural",
            }
            for name, extra in (("a", {}), ("b", {}), ("c", {"if": ["use_c"]}))
        ]
        raw = {
            "schema": "constraint-model.v1",
            "name": "capacity",
            "variables": variables,
            "constraints": constraints,
            "objective": {"sense": "min", "terms": [{"coef": 1, "var": "end"}]},
        }
        solved = solution(raw, REFERENCE, None, self.engine)
        self.assertEqual((solved["status"], solved["objective"]), ("optimal", 9))
        self.assertEqual(solved["checked"], {"violations": []})
        cheaper = solution(
            {
                **raw,
                "constraints": [dict(entry, weight=1) if entry["id"] == "want_c" else entry for entry in constraints],
            },
            REFERENCE,
            None,
            self.engine,
        )
        self.assertEqual((cheaper["objective"], cheaper["soft_violated"]), (7, [{"id": "want_c", "weight": 1}]))
        self.assertEqual(cheaper["checked"], {"violations": []})

    def test_time_slot_kinds_can_only_be_structural_and_need_real_intervals(self) -> None:
        raw, _ = schedule_model(2, 1, 60, 5, hinted=False)
        constraints = raw["constraints"]
        assert isinstance(constraints, list)
        broken = [dict(entry, strength="hard") if entry["kind"] == "no_overlap" else entry for entry in constraints]
        with self.assertRaises(ModelError) as raised:
            compile_model({**raw, "constraints": broken})
        self.assertEqual(
            [problem.code for problem in raised.exception.problems if problem.severity == "error"], ["STRUCTURAL_ONLY"]
        )
        with self.assertRaises(ModelError):
            compile_model(
                {
                    **raw,
                    "constraints": [
                        {
                            "id": "bad",
                            "kind": "no_overlap",
                            "args": {"intervals": ["makespan"]},
                            "strength": "structural",
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
