from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from ambitious_kit.domain.envelope import Failure, failure

from ambitious_constraints.domain.check import check
from ambitious_constraints.domain.explain import Conflicts, Oracle, enumerate_conflicts, flips
from ambitious_constraints.domain.model import (
    SOLUTION_SCHEMA,
    Compiled,
    ModelError,
    apply_overrides,
    compile_model,
    evidence_for,
    rests_on_assumption,
    scenario_names,
    scenario_overrides,
)

type Status = Literal["optimal", "feasible", "infeasible", "unknown"]

CONFIDENCE_ORDER = ("assumption", "derived", "sourced")


class Undecided(Exception):
    pass


@dataclass(frozen=True)
class Outcome:
    status: Status
    objective: int | None
    bound: int | None
    values: Mapping[str, int]
    soft_off: tuple[str, ...]


class Engine(Protocol):
    def version(self) -> str: ...

    def lock_sha256(self) -> str: ...

    def solve(self, model: Compiled, seed: int, deterministic_time: int) -> Outcome: ...

    def oracle(self, model: Compiled, seed: int, deterministic_time: int) -> Oracle: ...


@dataclass(frozen=True)
class Run:
    engine: Engine
    seed: int
    deterministic_time: int

    def solver(self) -> dict[str, object]:
        return {
            "name": "cp-sat",
            "version": self.engine.version(),
            "seed": self.seed,
            "workers": 1,
            "deterministic_time_limit": self.deterministic_time,
            "runtime_lock_sha256": self.engine.lock_sha256(),
        }


def model_failure(error: ModelError) -> Failure:
    errors = [problem for problem in error.problems if problem.severity == "error"]
    return failure(
        "E_MODEL",
        f"The model has {len(errors)} problem(s). The first is: {errors[0].message}",
        "Run model validate, fix every problem with severity error, and try again.",
        {"problems": [problem.to_json() for problem in error.problems]},
    )


def undecided(run: Run) -> Failure:
    return failure(
        "E_LIMIT",
        f"The solver could not decide within the deterministic time limit of {run.deterministic_time}.",
        "Raise limits.deterministic_time, or make the model smaller.",
    )


def prepare(
    raw: Mapping[str, object], scenario: str | None, extra: Mapping[str, object] | None = None
) -> tuple[Mapping[str, object], Compiled]:
    try:
        compile_model(raw)
        adjusted: Mapping[str, object] = raw
        if scenario is not None:
            overrides = scenario_overrides(raw, scenario)
            if overrides is None:
                raise failure(
                    "E_NOT_FOUND",
                    f'The model has no scenario named "{scenario}".',
                    f"Use one of: {', '.join(scenario_names(raw)) or 'the model defines no scenarios'}.",
                )
            adjusted = apply_overrides(adjusted, overrides)
        if extra is not None:
            adjusted = apply_overrides(adjusted, extra)
        return adjusted, compile_model(adjusted)[0]
    except ModelError as error:
        raise model_failure(error) from error


def shown_values(model: Compiled, values: Mapping[str, int]) -> dict[str, object]:
    shown: dict[str, object] = {}
    for variable in model.variables:
        if variable.name not in values:
            continue
        value = values[variable.name]
        if variable.type == "bool":
            shown[variable.name] = value == 1
        elif variable.type == "enum":
            shown[variable.name] = variable.values[value]
        else:
            shown[variable.name] = value
    return shown


def assumption_ids(raw: Mapping[str, object], model: Compiled) -> list[str]:
    return [
        constraint.id
        for constraint in model.constraints
        if constraint.strength != "structural" and rests_on_assumption(raw, constraint)
    ]


def solution(
    raw: Mapping[str, object],
    reference: Mapping[str, object],
    scenario: str | None,
    run: Run,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    adjusted, model = prepare(raw, scenario, extra)
    outcome = run.engine.solve(model, run.seed, run.deterministic_time)
    weights = {constraint.id: constraint.weight for constraint in model.constraints}
    violations: list[dict[str, str]] = []
    soft = list(outcome.soft_off)
    if outcome.status in ("optimal", "feasible"):
        checked = check(model, outcome.values)
        violations = [violation.to_json() for violation in checked.violations]
        violations += [
            {"constraint": name, "message": "the solver reported this soft constraint as kept, but its values break it"}
            for name in checked.soft_violated
            if name not in outcome.soft_off
        ]
        if not checked.violations and checked.objective is not None and outcome.objective is not None:
            recomputed = checked.objective
            if recomputed != outcome.objective and set(checked.soft_violated) == set(outcome.soft_off):
                violations.append(
                    {
                        "constraint": "objective",
                        "message": f"the solver reported {outcome.objective}, the values give {recomputed}",
                    }
                )
    return {
        "schema": SOLUTION_SCHEMA,
        "model": dict(reference),
        "scenario": scenario,
        "status": outcome.status,
        "objective": outcome.objective,
        "bound": outcome.bound,
        "values": shown_values(model, outcome.values),
        "soft_violated": [{"id": name, "weight": weights[name]} for name in soft],
        "checked": {"violations": violations},
        "rests_on_assumptions": assumption_ids(adjusted, model),
        "solver": run.solver(),
    }


def _member(raw: Mapping[str, object], model: Compiled, identifier: str, levers: frozenset[str]) -> dict[str, object]:
    constraint = next(found for found in model.constraints if found.id == identifier)
    evidence = evidence_for(raw, constraint)
    stated = [entry.get("confidence") for entry in evidence]
    confidence = next((level for level in CONFIDENCE_ORDER if level in stated), "none")
    return {
        "id": identifier,
        "label": constraint.label,
        "category": constraint.category,
        "negotiable": constraint.negotiable,
        "lever": identifier in levers,
        "confidence": confidence,
        "rests_on_assumption": rests_on_assumption(raw, constraint),
        "evidence": evidence,
    }


def _set(raw: Mapping[str, object], model: Compiled, ids: Sequence[str], levers: frozenset[str]) -> dict[str, object]:
    members = [_member(raw, model, identifier, levers) for identifier in ids]
    return {
        "ids": list(ids),
        "members": members,
        "rests_on_assumptions": [member["id"] for member in members if member["rests_on_assumption"] is True],
    }


def explain(
    raw: Mapping[str, object],
    reference: Mapping[str, object],
    scenario: str | None,
    run: Run,
    max_sets: int,
    max_depth: int,
) -> dict[str, object]:
    adjusted, model = prepare(raw, scenario)
    hard = frozenset(constraint.id for constraint in model.constraints if constraint.strength == "hard")
    levers = model.levers()
    try:
        found: Conflicts = enumerate_conflicts(
            run.engine.oracle(model, run.seed, run.deterministic_time), hard, levers, max_sets, max_depth
        )
    except Undecided as error:
        raise undecided(run) from error
    feasible = len(found.mus) == 0
    mus = [_set(adjusted, model, ids, levers) for ids in found.mus]
    mcs = [] if feasible else [_set(adjusted, model, ids, levers) for ids in found.mcs]
    resting = sorted({identifier for entry in mus for identifier in _strings(entry["rests_on_assumptions"])})
    return {
        "model": dict(reference),
        "scenario": scenario,
        "status": "feasible" if feasible else "infeasible",
        "mus": mus,
        "mcs": mcs,
        "structural_conflict": any(len(ids) == 0 for ids in found.mus),
        "complete": found.complete,
        "levers": sorted(levers),
        "rests_on_assumptions": resting,
        "solver": run.solver(),
    }


def _strings(value: object) -> list[str]:
    return [entry for entry in value if isinstance(entry, str)] if isinstance(value, list) else []


def whatif(
    raw: Mapping[str, object],
    reference: Mapping[str, object],
    scenarios: Sequence[tuple[str | None, Mapping[str, object] | None]],
    run: Run,
) -> dict[str, object]:
    results = [
        solution(raw, reference, name if extra is None else None, run, extra) | {"scenario": name}
        for name, extra in scenarios
    ]
    names: set[str] = set()
    for result in results:
        values = result["values"]
        names |= set(values) if isinstance(values, dict) else set()
    differing: dict[str, list[object]] = {}
    for name in sorted(names):
        column = [values.get(name) if isinstance(values := result["values"], dict) else None for result in results]
        solved = [
            value for value, result in zip(column, results, strict=True) if result["status"] in ("optimal", "feasible")
        ]
        if any(value != solved[0] for value in solved):
            differing[name] = column
    return {
        "model": dict(reference),
        "scenarios": [result["scenario"] for result in results],
        "results": results,
        "differences": differing,
    }


def sweep(
    raw: Mapping[str, object],
    reference: Mapping[str, object],
    scenario: str | None,
    param: str,
    grid: Sequence[int],
    run: Run,
) -> dict[str, object]:
    base, model = prepare(raw, scenario)
    if param not in model.params:
        raise failure(
            "E_NOT_FOUND",
            f'The model has no parameter named "{param}".',
            f"Use one of: {', '.join(model.params) or 'the model defines no parameters'}.",
        )
    points: list[dict[str, object]] = []
    for value in grid:
        solved = solution(base, reference, None, run, {"params": {param: value}})
        if solved["status"] == "unknown":
            raise undecided(run)
        points.append(
            {
                "value": value,
                "status": solved["status"],
                "objective": solved["objective"],
                "values": solved["values"],
                "soft_violated": solved["soft_violated"],
                "violations": solved["checked"],
            }
        )
    return {
        "model": dict(reference),
        "scenario": scenario,
        "param": param,
        "base_value": model.params[param],
        "points": points,
        "flips": flips([(int(str(point["value"])), str(point["status"])) for point in points]),
        "rests_on_assumptions": assumption_ids(base, model),
        "solver": run.solver(),
    }
