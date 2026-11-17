from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ambitious_constraints.domain.model import (
    Compiled,
    Constraint,
    Cumulative,
    Element,
    FixLit,
    FixVar,
    Implication,
    Interval,
    Linear,
    Lit,
    NoOverlap,
    Pick,
    Precedence,
    Product,
    Row,
    Term,
)


@dataclass(frozen=True)
class Violation:
    constraint: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"constraint": self.constraint, "message": self.message}


@dataclass(frozen=True)
class Checked:
    violations: tuple[Violation, ...]
    soft_violated: tuple[str, ...]
    objective: int | None


class _Values:
    def __init__(self, model: Compiled, values: Mapping[str, int]) -> None:
        self.model = model
        self.values = values
        self.variables = model.by_name()

    def lit(self, lit: Lit) -> bool:
        value = self.values[lit.var]
        holds = value == 1 if lit.index is None else value == lit.index
        return holds != lit.negated

    def term(self, term: Term) -> int:
        value = self.values[term.var]
        return term.coef * (value if term.index is None else (1 if value == term.index else 0))

    def interval(self, name: str) -> Interval:
        interval = self.variables[name].interval
        if interval is None:
            raise KeyError(name)
        return interval

    def present(self, name: str) -> bool:
        present = self.interval(name).present
        return present is None or self.lit(present)

    def span(self, name: str) -> tuple[int, int]:
        interval = self.interval(name)
        return self.values[interval.start], self.values[interval.end]

    def row(self, row: Row) -> str | None:
        if isinstance(row, Linear):
            if not all(self.lit(lit) for lit in row.when):
                return None
            total = sum(self.term(term) for term in row.terms)
            holds = {"<=": total <= row.rhs, ">=": total >= row.rhs, "==": total == row.rhs, "!=": total != row.rhs}[
                row.op
            ]
            return None if holds else f"the left side is {total}, which is not {row.op} {row.rhs}"
        if isinstance(row, FixLit):
            if all(self.lit(lit) for lit in row.when) and not self.lit(row.lit):
                return f"{row.lit.var} does not have the fixed value"
            return None
        if isinstance(row, FixVar):
            actual = self.term(row.term)
            if all(self.lit(lit) for lit in row.when) and actual != row.value:
                return f"{row.term.var} is {actual}, not the fixed value {row.value}"
            return None
        if isinstance(row, Implication):
            if not all(self.lit(lit) for lit in row.when):
                return None
            met = [self.lit(lit) for lit in row.then]
            return (
                None if (all(met) if row.every else any(met)) else "the condition holds but what must follow does not"
            )
        if isinstance(row, Pick):
            if not all(self.lit(lit) for lit in row.when):
                return None
            chosen = sum(1 for lit in row.lits if self.lit(lit))
            if chosen > 1 or (row.exactly and chosen != 1):
                return f"{chosen} of the options are chosen"
            return None
        if isinstance(row, Product):
            expected = self.values[row.factors[0]] * self.values[row.factors[1]]
            actual = self.values[row.target]
            return (
                None
                if actual == expected
                else f"{row.target} is {actual}, but the product of its factors is {expected}"
            )
        if isinstance(row, Element):
            index = self.values[row.index]
            if not 0 <= index < len(row.values):
                return f"{row.index} is {index}, outside the table"
            actual = self.values[row.target]
            return (
                None
                if actual == row.values[index]
                else f"{row.target} is {actual}, but the table gives {row.values[index]}"
            )
        if isinstance(row, Precedence):
            if (
                not all(self.lit(lit) for lit in row.when)
                or not self.present(row.before)
                or not self.present(row.after)
            ):
                return None
            end, start = self.span(row.before)[1], self.span(row.after)[0]
            return (
                None if end + row.gap <= start else f"{row.before} ends at {end}, after {row.after} starts at {start}"
            )
        if isinstance(row, NoOverlap):
            spans = sorted((*self.span(name), name) for name in row.intervals if self.present(name))
            for (_, end, name), (start, _, other) in zip(spans, spans[1:], strict=False):
                if start < end:
                    return f"{name} and {other} overlap"
            return None
        return self.cumulative(row)

    def cumulative(self, row: Cumulative) -> str | None:
        active = [
            (*self.span(name), demand)
            for name, demand in zip(row.intervals, row.demands, strict=True)
            if self.present(name)
        ]
        for start, _, _ in active:
            load = sum(demand for begin, end, demand in active if begin <= start < end)
            if load > row.capacity:
                return f"the load at {start} is {load}, above the capacity {row.capacity}"
        return None

    def constraint(self, constraint: Constraint) -> str | None:
        for row in constraint.rows:
            problem = self.row(row)
            if problem is not None:
                return problem
        return None


def check(model: Compiled, values: Mapping[str, int], disabled: frozenset[str] = frozenset()) -> Checked:
    violations: list[Violation] = []
    for variable in model.variables:
        if variable.interval is not None:
            continue
        value = values.get(variable.name)
        if value is None:
            violations.append(Violation(variable.name, f"the variable {variable.name} has no value"))
        elif not any(lo <= value <= hi for lo, hi in variable.ranges):
            violations.append(Violation(variable.name, f"the variable {variable.name} is {value}, outside its domain"))
    if violations:
        return Checked(tuple(violations), (), None)
    reader = _Values(model, values)
    for variable in model.variables:
        interval = variable.interval
        if interval is not None and reader.present(variable.name):
            start, end = reader.span(variable.name)
            if start + interval.size != end:
                violations.append(
                    Violation(
                        variable.name,
                        f"the interval {variable.name} runs {start} to {end}, not its size {interval.size}",
                    )
                )
    soft: list[str] = []
    for constraint in model.constraints:
        if constraint.id in disabled:
            continue
        problem = reader.constraint(constraint)
        if problem is None:
            continue
        if constraint.strength == "soft":
            soft.append(constraint.id)
        else:
            violations.append(Violation(constraint.id, f"{constraint.label}: {problem}"))
    return Checked(tuple(violations), tuple(soft), objective_value(model, values, frozenset(soft)))


def objective_value(model: Compiled, values: Mapping[str, int], soft_violated: frozenset[str]) -> int | None:
    penalty = sum(constraint.weight for constraint in model.constraints if constraint.id in soft_violated)
    has_soft = any(constraint.strength == "soft" for constraint in model.constraints)
    if model.objective is None:
        return penalty if has_soft else None
    reader = _Values(model, values)
    total = sum(reader.term(term) for term in model.objective.terms)
    return total - penalty if model.objective.maximize else total + penalty
