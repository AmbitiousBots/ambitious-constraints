from __future__ import annotations

import ortools
from ortools.sat.python import cp_model

from ambitious_constraints.domain.analysis import Outcome, Status, Undecided
from ambitious_constraints.domain.model import (
    Compiled,
    Cumulative,
    Element,
    FixLit,
    FixVar,
    Implication,
    Linear,
    Lit,
    NoOverlap,
    Pick,
    Precedence,
    Product,
    Row,
    Term,
)

MAX_CPSAT_SEED = 2**31 - 1


def solver_version() -> str:
    return str(ortools.__version__)


class Built:
    def __init__(self, model: Compiled, *, optimize: bool) -> None:
        self.model = model
        self.cp = cp_model.CpModel()
        self.vars: dict[str, cp_model.IntVar] = {}
        self.enum_lits: dict[tuple[str, int], cp_model.IntVar] = {}
        self.intervals: dict[str, cp_model.IntervalVar] = {}
        self.assumptions: dict[str, cp_model.IntVar] = {}
        self.soft: dict[str, cp_model.IntVar] = {}
        for variable in model.variables:
            if variable.type == "bool":
                self.vars[variable.name] = self.cp.NewBoolVar(variable.name)
            elif variable.type == "int":
                domain = cp_model.Domain.FromIntervals([list(pair) for pair in variable.ranges])
                self.vars[variable.name] = self.cp.NewIntVarFromDomain(domain, variable.name)
            elif variable.type == "enum":
                index = self.cp.NewIntVar(0, len(variable.values) - 1, variable.name)
                self.vars[variable.name] = index
                literals = []
                for position, value in enumerate(variable.values):
                    literal = self.cp.NewBoolVar(f"{variable.name}={value}")
                    self.cp.Add(index == position).OnlyEnforceIf(literal)
                    self.cp.Add(index != position).OnlyEnforceIf(literal.Not())
                    self.enum_lits[(variable.name, position)] = literal
                    literals.append(literal)
                self.cp.AddExactlyOne(literals)
        for variable in model.variables:
            interval = variable.interval
            if interval is None:
                continue
            start, end = self.vars[interval.start], self.vars[interval.end]
            if interval.present is None:
                self.intervals[variable.name] = self.cp.NewIntervalVar(start, interval.size, end, variable.name)
            else:
                self.intervals[variable.name] = self.cp.NewOptionalIntervalVar(
                    start, interval.size, end, self.lit(interval.present), variable.name
                )
        for constraint in model.constraints:
            gate = None
            if constraint.strength == "hard":
                gate = self.assumptions[constraint.id] = self.cp.NewBoolVar(f"A_{constraint.id}")
            elif constraint.strength == "soft":
                gate = self.soft[constraint.id] = self.cp.NewBoolVar(f"S_{constraint.id}")
            for row in constraint.rows:
                self.add(row, gate)
        for hinted, hint in model.hints.items():
            self.cp.AddHint(self.vars[hinted], hint)
        self.objective = self.objective_expression() if optimize else None
        if self.objective is not None:
            if model.objective is not None and model.objective.maximize:
                self.cp.Maximize(self.objective)
            else:
                self.cp.Minimize(self.objective)

    def objective_expression(self) -> cp_model.LinearExprT | None:
        weights = {constraint.id: constraint.weight for constraint in self.model.constraints}
        penalty = sum(weights[name] * (1 - gate) for name, gate in self.soft.items())
        if self.model.objective is None:
            return penalty if self.soft else None
        total = sum(self.term(term) for term in self.model.objective.terms)
        return total - penalty if self.model.objective.maximize else total + penalty

    def lit(self, lit: Lit) -> cp_model.LiteralT:
        base = self.vars[lit.var] if lit.index is None else self.enum_lits[(lit.var, lit.index)]
        return base.Not() if lit.negated else base

    def term(self, term: Term) -> cp_model.LinearExprT:
        base = self.vars[term.var] if term.index is None else self.enum_lits[(term.var, term.index)]
        return term.coef * base

    def add(self, row: Row, gate: cp_model.IntVar | None) -> None:
        extra = [] if gate is None else [gate]
        if isinstance(row, Linear):
            total = sum(self.term(term) for term in row.terms)
            relation = {"<=": total <= row.rhs, ">=": total >= row.rhs, "==": total == row.rhs, "!=": total != row.rhs}[
                row.op
            ]
            self.enforce(self.cp.Add(relation), [self.lit(lit) for lit in row.when] + extra)
        elif isinstance(row, FixLit):
            self.enforce(self.cp.AddBoolAnd([self.lit(row.lit)]), [self.lit(lit) for lit in row.when] + extra)
        elif isinstance(row, FixVar):
            self.enforce(self.cp.Add(self.term(row.term) == row.value), [self.lit(lit) for lit in row.when] + extra)
        elif isinstance(row, Implication):
            before = [self.lit(lit).Not() for lit in row.when]
            after = [self.lit(lit) for lit in row.then]
            for group in [[lit] for lit in after] if row.every else [after]:
                self.enforce(self.cp.AddBoolOr(before + group), extra)
        elif isinstance(row, Pick):
            lits = [self.lit(lit) for lit in row.lits]
            enforced = [self.lit(lit) for lit in row.when] + extra
            if enforced:
                chosen = sum(lits)
                self.enforce(self.cp.Add(chosen == 1 if row.exactly else chosen <= 1), enforced)
            elif row.exactly:
                self.cp.AddExactlyOne(lits)
            else:
                self.cp.AddAtMostOne(lits)
        elif isinstance(row, Product):
            self.cp.AddMultiplicationEquality(self.vars[row.target], [self.vars[name] for name in row.factors])
        elif isinstance(row, Element):
            self.cp.AddElement(self.vars[row.index], list(row.values), self.vars[row.target])
        elif isinstance(row, Precedence):
            before_shape, after_shape = (
                self.model.variable(row.before).interval,
                self.model.variable(row.after).interval,
            )
            if before_shape is None or after_shape is None:
                return
            enforced = [self.lit(lit) for lit in row.when] + extra
            enforced += [self.lit(shape.present) for shape in (before_shape, after_shape) if shape.present is not None]
            self.enforce(self.cp.Add(self.vars[before_shape.end] + row.gap <= self.vars[after_shape.start]), enforced)
        elif isinstance(row, NoOverlap):
            self.cp.AddNoOverlap([self.intervals[name] for name in row.intervals])
        elif isinstance(row, Cumulative):
            self.cp.AddCumulative([self.intervals[name] for name in row.intervals], list(row.demands), row.capacity)

    def enforce(self, constraint: cp_model.Constraint, literals: list[cp_model.LiteralT]) -> None:
        if literals:
            constraint.OnlyEnforceIf(literals)

    def run(self, seed: int, deterministic_time: int, active: frozenset[str] | None) -> tuple[cp_model.CpSolver, int]:
        chosen = sorted(self.assumptions) if active is None else sorted(active & set(self.assumptions))
        self.cp.ClearAssumptions()
        self.cp.AddAssumptions([self.assumptions[name] for name in chosen])
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = 1
        solver.parameters.random_seed = seed % MAX_CPSAT_SEED
        solver.parameters.max_deterministic_time = float(deterministic_time)
        return solver, int(solver.Solve(self.cp))


def _status(code: int) -> Status:
    if code == cp_model.OPTIMAL:
        return "optimal"
    if code == cp_model.FEASIBLE:
        return "feasible"
    if code == cp_model.INFEASIBLE:
        return "infeasible"
    return "unknown"


def solve(model: Compiled, seed: int, deterministic_time: int) -> Outcome:
    built = Built(model, optimize=True)
    solver, code = built.run(seed, deterministic_time, None)
    status = _status(code)
    if status in ("infeasible", "unknown"):
        return Outcome(status, None, None, {}, ())
    values = {name: int(solver.Value(variable)) for name, variable in sorted(built.vars.items())}
    soft_off = tuple(name for name, gate in sorted(built.soft.items()) if not solver.Value(gate))
    if built.objective is None:
        return Outcome("optimal" if status == "optimal" else status, None, None, values, soft_off)
    return Outcome(
        status, int(round(solver.ObjectiveValue())), int(round(solver.BestObjectiveBound())), values, soft_off
    )


class ConflictOracle:
    def __init__(self, model: Compiled, seed: int, deterministic_time: int) -> None:
        self.built = Built(model, optimize=False)
        self.seed = seed
        self.deterministic_time = deterministic_time
        self.hard = frozenset(self.built.assumptions)
        self.solves = 0

    def core(self, active: frozenset[str]) -> frozenset[str] | None:
        self.solves += 1
        solver, code = self.built.run(self.seed, self.deterministic_time, active)
        status = _status(code)
        if status == "unknown":
            raise Undecided
        if status != "infeasible":
            return None
        by_index = {self.built.assumptions[name].Index(): name for name in active if name in self.built.assumptions}
        found = frozenset(
            by_index[index] for index in solver.SufficientAssumptionsForInfeasibility() if index in by_index
        )
        return found if found else frozenset(active & self.hard)
