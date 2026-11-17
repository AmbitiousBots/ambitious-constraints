from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

MODEL_SCHEMA = "constraint-model.v1"
SOLUTION_SCHEMA = "constraint-solution.v1"
MAX_VARIABLES = 20_000
MAX_CONSTRAINTS = 50_000
MAX_ROWS = 200_000
MAX_MAGNITUDE = 2**53
STRUCTURAL_ONLY = frozenset({"product", "element", "no_overlap", "cumulative"})
OPERATORS = ("<=", ">=", "==", "!=")
LEVER_CATEGORIES = frozenset({"desire", "goal"})

type Strength = Literal["structural", "hard", "soft"]
type VariableType = Literal["bool", "int", "enum", "interval"]


@dataclass(frozen=True)
class Problem:
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str

    def to_json(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "path": self.path, "message": self.message}


class ModelError(Exception):
    def __init__(self, problems: Sequence[Problem]) -> None:
        super().__init__("; ".join(problem.message for problem in problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Lit:
    var: str
    index: int | None
    negated: bool


@dataclass(frozen=True)
class Term:
    coef: int
    var: str
    index: int | None


@dataclass(frozen=True)
class Interval:
    start: str
    size: int
    end: str
    present: Lit | None


@dataclass(frozen=True)
class Variable:
    name: str
    type: VariableType
    ranges: tuple[tuple[int, int], ...]
    values: tuple[str, ...]
    interval: Interval | None


@dataclass(frozen=True)
class Linear:
    terms: tuple[Term, ...]
    op: str
    rhs: int
    when: tuple[Lit, ...]


@dataclass(frozen=True)
class FixLit:
    lit: Lit
    when: tuple[Lit, ...]


@dataclass(frozen=True)
class FixVar:
    term: Term
    value: int
    when: tuple[Lit, ...]


@dataclass(frozen=True)
class Implication:
    when: tuple[Lit, ...]
    then: tuple[Lit, ...]
    every: bool


@dataclass(frozen=True)
class Pick:
    exactly: bool
    lits: tuple[Lit, ...]
    when: tuple[Lit, ...]


@dataclass(frozen=True)
class Product:
    target: str
    factors: tuple[str, str]


@dataclass(frozen=True)
class Element:
    index: str
    values: tuple[int, ...]
    target: str


@dataclass(frozen=True)
class Precedence:
    before: str
    after: str
    gap: int
    when: tuple[Lit, ...]


@dataclass(frozen=True)
class NoOverlap:
    intervals: tuple[str, ...]


@dataclass(frozen=True)
class Cumulative:
    intervals: tuple[str, ...]
    demands: tuple[int, ...]
    capacity: int


type Row = Linear | FixLit | FixVar | Implication | Pick | Product | Element | Precedence | NoOverlap | Cumulative


@dataclass(frozen=True)
class Constraint:
    id: str
    strength: Strength
    weight: int
    category: str | None
    negotiable: bool
    label: str
    rows: tuple[Row, ...]
    params: tuple[str, ...]


@dataclass(frozen=True)
class Objective:
    maximize: bool
    terms: tuple[Term, ...]


@dataclass(frozen=True)
class Compiled:
    name: str
    variables: tuple[Variable, ...]
    params: Mapping[str, int]
    constraints: tuple[Constraint, ...]
    objective: Objective | None
    hints: Mapping[str, int]

    def variable(self, name: str) -> Variable:
        return self.by_name()[name]

    def by_name(self) -> dict[str, Variable]:
        return {variable.name: variable for variable in self.variables}

    def levers(self) -> frozenset[str]:
        return frozenset(
            constraint.id
            for constraint in self.constraints
            if constraint.strength == "hard" and constraint.negotiable and constraint.category in LEVER_CATEGORIES
        )


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_of(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _records(value: object) -> list[Mapping[str, object]]:
    return [entry for entry in value if isinstance(entry, Mapping)] if isinstance(value, list) else []


class _Compiler:
    def __init__(self, raw: Mapping[str, object]) -> None:
        self.raw = raw
        self.problems: list[Problem] = []
        self.params: dict[str, int] = {}
        self.variables: dict[str, Variable] = {}
        self.used_params: set[str] = set()

    def error(self, code: str, path: str, message: str) -> None:
        self.problems.append(Problem("error", code, path, message))

    def warn(self, code: str, path: str, message: str) -> None:
        self.problems.append(Problem("warning", code, path, message))

    def number(self, value: object, path: str) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            if abs(value) > MAX_MAGNITUDE:
                self.error("NUMBER_TOO_LARGE", path, f"The number at {path} is larger than {MAX_MAGNITUDE}.")
                return 0
            return value
        if isinstance(value, str):
            negative = value.startswith("-")
            name = value.removeprefix("-").removeprefix("param:")
            if name in self.params:
                self.used_params.add(name)
                return -self.params[name] if negative else self.params[name]
            self.error("UNKNOWN_PARAM", path, f'{path} names the parameter "{name}", which the model does not define.')
            return 0
        self.error("NOT_A_NUMBER", path, f"{path} must be an integer or param:<name>.")
        return 0

    def lit(self, value: object, path: str) -> Lit | None:
        if not isinstance(value, str):
            self.error(
                "NOT_A_LITERAL", path, f"{path} must be a literal: a boolean variable, name=value, or either with !."
            )
            return None
        negated = value.startswith("!")
        name, _, chosen = value.removeprefix("!").partition("=")
        variable = self.variables.get(name)
        if variable is None:
            self.error(
                "UNKNOWN_VARIABLE", path, f'{path} names the variable "{name}", which the model does not define.'
            )
            return None
        if chosen == "":
            if variable.type != "bool":
                self.error("NOT_BOOLEAN", path, f'{path} uses "{name}" as a literal, but it is not a boolean variable.')
                return None
            return Lit(name, None, negated)
        if variable.type != "enum" or chosen not in variable.values:
            self.error("UNKNOWN_ENUM_VALUE", path, f'{path}: "{chosen}" is not a value of the enum variable "{name}".')
            return None
        return Lit(name, variable.values.index(chosen), negated)

    def lits(self, value: object, path: str, *, required: bool) -> tuple[Lit, ...]:
        if value is None and not required:
            return ()
        if not isinstance(value, list) or (required and len(value) == 0):
            self.error(
                "NOT_A_LIST",
                path,
                f"{path} must be a list of literals{' with at least one entry' if required else ''}.",
            )
            return ()
        found = [self.lit(entry, f"{path}/{index}") for index, entry in enumerate(value)]
        return tuple(lit for lit in found if lit is not None)

    def term(self, coef: object, name: object, path: str) -> Term | None:
        factor = self.number(coef, f"{path}/coef")
        if not isinstance(name, str) or name.startswith("!"):
            self.error("NOT_A_TERM", path, f"{path} must name an integer variable, a boolean variable or name=value.")
            return None
        base, _, chosen = name.partition("=")
        variable = self.variables.get(base)
        if variable is None:
            self.error(
                "UNKNOWN_VARIABLE", path, f'{path} names the variable "{base}", which the model does not define.'
            )
            return None
        if chosen != "":
            if variable.type != "enum" or chosen not in variable.values:
                self.error(
                    "UNKNOWN_ENUM_VALUE", path, f'{path}: "{chosen}" is not a value of the enum variable "{base}".'
                )
                return None
            return Term(factor, base, variable.values.index(chosen))
        if variable.type not in ("int", "bool"):
            self.error(
                "NOT_NUMERIC", path, f'{path} uses "{base}" in arithmetic, but it is a {variable.type} variable.'
            )
            return None
        return Term(factor, base, None)

    def int_var(self, value: object, path: str) -> str:
        variable = self.variables.get(value) if isinstance(value, str) else None
        if variable is None or variable.type != "int":
            self.error("NOT_AN_INT_VARIABLE", path, f"{path} must name an int variable of the model.")
            return ""
        return variable.name

    def interval(self, value: object, path: str, *, sized: bool) -> str:
        variable = self.variables.get(value) if isinstance(value, str) else None
        if variable is None or variable.interval is None:
            self.error("NOT_AN_INTERVAL", path, f"{path} must name an interval variable of the model.")
            return ""
        if sized and variable.interval.size < 1:
            self.error(
                "EMPTY_INTERVAL",
                path,
                f'{path}: the interval "{variable.name}" has size 0, so it cannot take part here.',
            )
        return variable.name

    def declare_variables(self) -> None:
        declared = _records(self.raw.get("variables"))
        if len(declared) > MAX_VARIABLES:
            self.error(
                "TOO_LARGE", "/variables", f"The model has {len(declared)} variables; the limit is {MAX_VARIABLES}."
            )
            return
        for index, entry in enumerate(declared):
            path = f"/variables/{index}"
            name, kind = entry.get("name"), entry.get("type")
            if not isinstance(name, str):
                continue
            if name in self.variables:
                self.error("DUPLICATE_VARIABLE", path, f'The variable "{name}" is declared more than once.')
                continue
            domain = entry.get("domain")
            fields: Mapping[str, object] = domain if isinstance(domain, Mapping) else {}
            if kind == "bool":
                self.variables[name] = Variable(name, "bool", ((0, 1),), (), None)
            elif kind == "enum":
                values = fields.get("values")
                names = tuple(value for value in values if isinstance(value, str)) if isinstance(values, list) else ()
                if (
                    not isinstance(values, list)
                    or len(names) != len(values)
                    or len(set(names)) != len(names)
                    or not names
                ):
                    self.error(
                        "BAD_DOMAIN", path, f'The enum variable "{name}" needs domain.values: a list of distinct names.'
                    )
                    continue
                self.variables[name] = Variable(name, "enum", ((0, len(names) - 1),), names, None)
            elif kind == "int":
                ranges = self.int_ranges(fields, path, name)
                if ranges:
                    self.variables[name] = Variable(name, "int", ranges, (), None)
        for index, entry in enumerate(declared):
            name, kind = entry.get("name"), entry.get("type")
            if kind != "interval" or not isinstance(name, str) or name in self.variables:
                continue
            path = f"/variables/{index}"
            shape = entry.get("interval")
            if not isinstance(shape, Mapping):
                self.error(
                    "BAD_INTERVAL",
                    path,
                    f'The interval variable "{name}" needs an interval field: start, size and end.',
                )
                continue
            start = self.int_var(shape.get("start"), f"{path}/interval/start")
            end = self.int_var(shape.get("end"), f"{path}/interval/end")
            size = shape.get("size")
            present = (
                None if shape.get("present") is None else self.lit(shape.get("present"), f"{path}/interval/present")
            )
            if start == "" or end == "" or not isinstance(size, int) or isinstance(size, bool):
                continue
            self.variables[name] = Variable(name, "interval", (), (), Interval(start, size, end, present))

    def int_ranges(self, fields: Mapping[str, object], path: str, name: str) -> tuple[tuple[int, int], ...]:
        lo, hi, values, ranges = fields.get("lo"), fields.get("hi"), fields.get("values"), fields.get("ranges")
        given = [key for key in ("values", "ranges") if fields.get(key) is not None]
        bounded = isinstance(lo, int) and isinstance(hi, int) and not isinstance(lo, bool) and not isinstance(hi, bool)
        if len(given) + (1 if lo is not None or hi is not None else 0) != 1:
            self.error(
                "BAD_DOMAIN", path, f'The int variable "{name}" needs exactly one of: lo and hi, values, or ranges.'
            )
            return ()
        pairs: list[tuple[int, int]] = []
        if isinstance(lo, int) and isinstance(hi, int) and bounded:
            pairs = [(lo, hi)]
        elif isinstance(values, list):
            numbers = sorted({value for value in values if isinstance(value, int) and not isinstance(value, bool)})
            if len(numbers) == 0 or any(not _is_int(value) for value in values):
                self.error("BAD_DOMAIN", path, f'The int variable "{name}" needs integer domain.values.')
                return ()
            pairs = [(value, value) for value in numbers]
        elif isinstance(ranges, list):
            for pair in ranges:
                if isinstance(pair, list) and len(pair) == 2:
                    first, last = pair[0], pair[1]
                    if (
                        isinstance(first, int)
                        and isinstance(last, int)
                        and not isinstance(first, bool)
                        and first <= last
                    ):
                        pairs.append((first, last))
                        continue
                self.error(
                    "BAD_DOMAIN", path, f'The int variable "{name}" has a range that is not [lo, hi] with lo <= hi.'
                )
                return ()
        merged: list[tuple[int, int]] = []
        for first, last in sorted(pairs):
            if merged and first <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], last))
            else:
                merged.append((first, last))
        if not merged or merged[0][0] > merged[-1][1]:
            self.error("BAD_DOMAIN", path, f'The int variable "{name}" has an empty domain.')
            return ()
        if abs(merged[0][0]) > MAX_MAGNITUDE or abs(merged[-1][1]) > MAX_MAGNITUDE:
            self.error("NUMBER_TOO_LARGE", path, f'The domain of "{name}" goes beyond {MAX_MAGNITUDE}.')
            return ()
        return tuple(merged)

    def declare_params(self) -> None:
        for index, entry in enumerate(_records(self.raw.get("params"))):
            name, value = entry.get("name"), entry.get("value")
            if not isinstance(name, str) or not isinstance(value, int) or isinstance(value, bool):
                continue
            if name in self.params:
                self.error("DUPLICATE_PARAM", f"/params/{index}", f'The parameter "{name}" is declared more than once.')
            self.params[name] = value

    def row(self, kind: object, args: Mapping[str, object], path: str) -> Row | None:
        when = () if kind == "implication" else self.lits(args.get("if"), f"{path}/if", required=False)
        if kind == "linear":
            raw_terms = args.get("terms")
            terms: list[Term] = []
            if not isinstance(raw_terms, list) or len(raw_terms) == 0:
                self.error(
                    "BAD_ARGS",
                    path,
                    f"{path}: a linear constraint needs terms, a list of [coefficient, variable] pairs.",
                )
                return None
            for index, pair in enumerate(raw_terms):
                if not isinstance(pair, list) or len(pair) != 2:
                    self.error(
                        "BAD_ARGS",
                        f"{path}/terms/{index}",
                        f"{path}/terms/{index} must be a [coefficient, variable] pair.",
                    )
                    continue
                term = self.term(pair[0], pair[1], f"{path}/terms/{index}")
                if term is not None:
                    terms.append(term)
            op = args.get("op")
            if not isinstance(op, str) or op not in OPERATORS:
                self.error("BAD_ARGS", f"{path}/op", f"{path}/op must be one of {', '.join(OPERATORS)}.")
                return None
            return Linear(tuple(terms), op, self.number(args.get("rhs"), f"{path}/rhs"), when)
        if kind == "fix":
            if "lit" in args:
                lit = self.lit(args.get("lit"), f"{path}/lit")
                return None if lit is None else FixLit(lit, when)
            term = self.term(1, args.get("var"), f"{path}/var")
            return None if term is None else FixVar(term, self.number(args.get("value"), f"{path}/value"), when)
        if kind == "implication":
            return Implication(
                self.lits(args.get("if"), f"{path}/if", required=True),
                self.lits(args.get("then"), f"{path}/then", required=True),
                args.get("all") is True,
            )
        if kind in ("exactly_one", "at_most_one"):
            return Pick(kind == "exactly_one", self.lits(args.get("lits"), f"{path}/lits", required=True), when)
        if kind == "product":
            factors = args.get("factors")
            if not isinstance(factors, list) or len(factors) != 2:
                self.error("BAD_ARGS", f"{path}/factors", f"{path}/factors must name exactly two int variables.")
                return None
            return Product(
                self.int_var(args.get("target"), f"{path}/target"),
                (self.int_var(factors[0], f"{path}/factors/0"), self.int_var(factors[1], f"{path}/factors/1")),
            )
        if kind == "element":
            values = args.get("values")
            if not isinstance(values, list) or len(values) == 0:
                self.error(
                    "BAD_ARGS", f"{path}/values", f"{path}/values must be a list of numbers with at least one entry."
                )
                return None
            return Element(
                self.int_var(args.get("index"), f"{path}/index"),
                tuple(self.number(value, f"{path}/values/{index}") for index, value in enumerate(values)),
                self.int_var(args.get("target"), f"{path}/target"),
            )
        if kind == "precedence":
            gap = args.get("gap")
            return Precedence(
                self.interval(args.get("before"), f"{path}/before", sized=False),
                self.interval(args.get("after"), f"{path}/after", sized=False),
                0 if gap is None else self.number(gap, f"{path}/gap"),
                when,
            )
        if kind in ("no_overlap", "cumulative"):
            listed = args.get("intervals")
            if not isinstance(listed, list) or len(listed) == 0:
                self.error("BAD_ARGS", f"{path}/intervals", f"{path}/intervals must be a list of interval variables.")
                return None
            names = tuple(
                self.interval(name, f"{path}/intervals/{index}", sized=True) for index, name in enumerate(listed)
            )
            if kind == "no_overlap":
                return NoOverlap(names)
            demands = args.get("demands")
            if not isinstance(demands, list) or len(demands) != len(listed):
                self.error("BAD_ARGS", f"{path}/demands", f"{path}/demands must give one number for each interval.")
                return None
            amounts = tuple(self.number(value, f"{path}/demands/{index}") for index, value in enumerate(demands))
            if any(amount < 0 for amount in amounts):
                self.error("BAD_ARGS", f"{path}/demands", f"{path}/demands must not be negative.")
            return Cumulative(names, amounts, self.number(args.get("capacity"), f"{path}/capacity"))
        self.error("UNKNOWN_KIND", path, f'{path}: "{kind}" is not a constraint kind.')
        return None

    def constraint(self, entry: Mapping[str, object], path: str, seen: set[str]) -> Constraint | None:
        identifier, kind, args, strength = entry.get("id"), entry.get("kind"), entry.get("args"), entry.get("strength")
        if not isinstance(identifier, str) or not isinstance(args, Mapping):
            return None
        if strength != "structural" and strength != "hard" and strength != "soft":
            return None
        if identifier in seen:
            self.error("DUPLICATE_CONSTRAINT", path, f'The constraint id "{identifier}" is used more than once.')
            return None
        seen.add(identifier)
        self.used_params = set()
        nested = args.get("rows")
        pieces: list[tuple[object, Mapping[str, object], str]] = []
        if nested is None:
            pieces.append((kind, args, f"{path}/args"))
        elif isinstance(nested, list) and len(nested) > 0:
            for index, piece in enumerate(nested):
                if not isinstance(piece, Mapping):
                    self.error("BAD_ARGS", f"{path}/args/rows/{index}", f"{path}/args/rows/{index} must be an object.")
                    continue
                pieces.append((piece.get("kind", kind), piece, f"{path}/args/rows/{index}"))
        else:
            self.error("BAD_ARGS", f"{path}/args/rows", f"{path}/args/rows must be a list with at least one entry.")
        rows: list[Row] = []
        for row_kind, row_args, row_path in pieces:
            if row_kind in STRUCTURAL_ONLY and strength != "structural":
                self.error(
                    "STRUCTURAL_ONLY",
                    row_path,
                    f'The constraint "{identifier}" is {strength}, but a {row_kind} constraint can only be structural.',
                )
                continue
            row = self.row(row_kind, row_args, row_path)
            if row is not None:
                rows.append(row)
        weight = entry.get("weight")
        category = entry.get("category")
        label = entry.get("label")
        return Constraint(
            identifier,
            strength,
            weight if isinstance(weight, int) and not isinstance(weight, bool) else 0,
            category if isinstance(category, str) else None,
            entry.get("negotiable") is not False,
            label if isinstance(label, str) and label != "" else identifier,
            tuple(rows),
            tuple(sorted(self.used_params)),
        )

    def compile(self) -> Compiled:
        self.declare_params()
        self.declare_variables()
        listed = _records(self.raw.get("constraints"))
        constraints: list[Constraint] = []
        seen: set[str] = set()
        if len(listed) > MAX_CONSTRAINTS:
            self.error(
                "TOO_LARGE", "/constraints", f"The model has {len(listed)} constraints; the limit is {MAX_CONSTRAINTS}."
            )
            listed = []
        for index, entry in enumerate(listed):
            built = self.constraint(entry, f"/constraints/{index}", seen)
            if built is not None:
                constraints.append(built)
        if sum(len(constraint.rows) for constraint in constraints) > MAX_ROWS:
            self.error("TOO_LARGE", "/constraints", f"The model has more than {MAX_ROWS} constraint rows.")
        objective: Objective | None = None
        stated = self.raw.get("objective")
        if isinstance(stated, Mapping):
            terms = [
                self.term(entry.get("coef"), entry.get("var"), f"/objective/terms/{index}")
                for index, entry in enumerate(_records(stated.get("terms")))
            ]
            objective = Objective(stated.get("sense") == "max", tuple(term for term in terms if term is not None))
        hints: dict[str, int] = {}
        given = self.raw.get("hints")
        for name, value in given.items() if isinstance(given, Mapping) else ():
            variable = self.variables.get(name)
            path = f"/hints/{name}"
            if variable is None or variable.type == "interval":
                self.error(
                    "UNKNOWN_VARIABLE", path, f'{path}: "{name}" is not a bool, int or enum variable of the model.'
                )
            elif variable.type == "enum" and isinstance(value, str) and value in variable.values:
                hints[name] = variable.values.index(value)
            elif variable.type == "bool" and isinstance(value, bool):
                hints[name] = 1 if value else 0
            elif variable.type == "int" and isinstance(value, int) and not isinstance(value, bool):
                hints[name] = value
            else:
                self.error("BAD_HINT", path, f'{path}: the hint does not fit the {variable.type} variable "{name}".')
        self.evidence(constraints)
        self.scenarios(seen)
        errors = [problem for problem in self.problems if problem.severity == "error"]
        if errors:
            raise ModelError(self.problems)
        name = self.raw.get("name")
        return Compiled(
            name if isinstance(name, str) else "",
            tuple(sorted(self.variables.values(), key=lambda variable: variable.name)),
            dict(sorted(self.params.items())),
            tuple(sorted(constraints, key=lambda constraint: constraint.id)),
            objective,
            dict(sorted(hints.items())),
        )

    def evidence(self, constraints: Sequence[Constraint]) -> None:
        ids = {constraint.id for constraint in constraints}
        backed_constraints: set[str] = set()
        backed_params: set[str] = set()
        for index, entry in enumerate(_records(self.raw.get("evidence"))):
            path = f"/evidence/{index}"
            target = entry.get("target")
            fields: Mapping[str, object] = target if isinstance(target, Mapping) else {}
            constraint, param = fields.get("constraint"), fields.get("param")
            if (constraint is None) == (param is None):
                self.error("BAD_EVIDENCE", path, f"{path}/target must name exactly one of constraint or param.")
            elif isinstance(constraint, str):
                if constraint not in ids:
                    self.error(
                        "UNKNOWN_CONSTRAINT", path, f'{path} is evidence for "{constraint}", which is not a constraint.'
                    )
                backed_constraints.add(constraint)
            elif isinstance(param, str):
                if param not in self.params:
                    self.error("UNKNOWN_PARAM", path, f'{path} is evidence for "{param}", which is not a parameter.')
                backed_params.add(param)
            inputs = entry.get("inputs")
            if entry.get("confidence") == "derived" and not (isinstance(inputs, list) and len(inputs) > 0):
                self.warn("DERIVED_WITHOUT_INPUTS", path, f"{path} is derived, but does not name its inputs.")
        for constraint_row in constraints:
            if constraint_row.category in ("assumption", "fact") and constraint_row.id not in backed_constraints:
                if not any(param in backed_params for param in constraint_row.params):
                    self.warn(
                        "NO_EVIDENCE",
                        f"/constraints/{constraint_row.id}",
                        f'The {constraint_row.category} "{constraint_row.id}" has no evidence, '
                        "so it is treated as an assumption.",
                    )
        for name in sorted(set(self.params) - backed_params):
            self.warn(
                "NO_EVIDENCE",
                f"/params/{name}",
                f'The parameter "{name}" has no evidence, so it is treated as an assumption.',
            )

    def scenarios(self, ids: set[str]) -> None:
        names: set[str] = set()
        for index, entry in enumerate(_records(self.raw.get("scenarios"))):
            path = f"/scenarios/{index}"
            name = entry.get("name")
            if isinstance(name, str):
                if name in names:
                    self.error("DUPLICATE_SCENARIO", path, f'The scenario "{name}" is declared more than once.')
                names.add(name)
            overrides = entry.get("overrides")
            fields: Mapping[str, object] = overrides if isinstance(overrides, Mapping) else {}
            for key in ("disable", "harden"):
                listed = fields.get(key)
                for identifier in listed if isinstance(listed, list) else []:
                    if identifier not in ids:
                        self.error(
                            "UNKNOWN_CONSTRAINT",
                            f"{path}/overrides/{key}",
                            f'{path} would {key} "{identifier}", which is not a constraint.',
                        )
            soften = fields.get("soften")
            for identifier in soften if isinstance(soften, Mapping) else {}:
                if identifier not in ids:
                    self.error(
                        "UNKNOWN_CONSTRAINT",
                        f"{path}/overrides/soften",
                        f'{path} would soften "{identifier}", which is not a constraint.',
                    )
            params = fields.get("params")
            for param in params if isinstance(params, Mapping) else {}:
                if param not in self.params:
                    self.error(
                        "UNKNOWN_PARAM", f"{path}/overrides/params", f'{path} sets "{param}", which is not a parameter.'
                    )
            added = fields.get("add")
            for extra in _records(added):
                if extra.get("id") in ids:
                    self.error(
                        "DUPLICATE_CONSTRAINT",
                        f"{path}/overrides/add",
                        f'{path} adds "{extra.get("id")}", which already exists.',
                    )


def compile_model(raw: Mapping[str, object]) -> tuple[Compiled, tuple[Problem, ...]]:
    compiler = _Compiler(raw)
    compiled = compiler.compile()
    return compiled, tuple(compiler.problems)


def semantic_problems(raw: Mapping[str, object]) -> tuple[Problem, ...]:
    try:
        return compile_model(raw)[1]
    except ModelError as error:
        return error.problems


def scenario_names(raw: Mapping[str, object]) -> list[str]:
    return [name for entry in _records(raw.get("scenarios")) if isinstance(name := entry.get("name"), str)]


def scenario_overrides(raw: Mapping[str, object], name: str) -> Mapping[str, object] | None:
    for entry in _records(raw.get("scenarios")):
        if entry.get("name") == name:
            overrides = entry.get("overrides")
            return overrides if isinstance(overrides, Mapping) else {}
    return None


def apply_overrides(raw: Mapping[str, object], overrides: Mapping[str, object]) -> dict[str, object]:
    copied: object = json.loads(json.dumps(raw))
    if not isinstance(copied, dict):
        return {}
    model: dict[str, object] = copied
    changed = overrides.get("params")
    values: Mapping[str, object] = changed if isinstance(changed, Mapping) else {}
    params = model.get("params")
    for entry in params if isinstance(params, list) else []:
        if isinstance(entry, dict) and entry.get("name") in values:
            entry["value"] = values[entry["name"]]
    disabled = overrides.get("disable")
    off = set(disabled) if isinstance(disabled, list) else set()
    soften = overrides.get("soften")
    softened: Mapping[str, object] = soften if isinstance(soften, Mapping) else {}
    harden = overrides.get("harden")
    hardened = set(harden) if isinstance(harden, list) else set()
    kept: list[object] = []
    listed = model.get("constraints")
    for entry in listed if isinstance(listed, list) else []:
        if not isinstance(entry, dict) or entry.get("id") in off:
            continue
        if entry.get("id") in softened:
            entry["strength"], entry["weight"] = "soft", softened[entry["id"]]
        if entry.get("id") in hardened:
            entry["strength"] = "hard"
        kept.append(entry)
    added = overrides.get("add")
    kept.extend(added if isinstance(added, list) else [])
    model["constraints"] = kept
    model.pop("scenarios", None)
    return model


def _keyed(raw: Mapping[str, object], section: str, key: str) -> dict[str, object]:
    return {str(entry.get(key)): entry for entry in _records(raw.get(section))}


def diff_models(old: Mapping[str, object] | None, new: Mapping[str, object]) -> dict[str, object]:
    before: Mapping[str, object] = {} if old is None else old
    result: dict[str, object] = {}
    for section, key in (("variables", "name"), ("params", "name"), ("constraints", "id"), ("scenarios", "name")):
        was, now = _keyed(before, section, key), _keyed(new, section, key)
        result[section] = {
            "added": sorted(set(now) - set(was)),
            "removed": sorted(set(was) - set(now)),
            "changed": sorted(name for name in set(was) & set(now) if canonical(was[name]) != canonical(now[name])),
        }
    result["objective_changed"] = canonical(before.get("objective")) != canonical(new.get("objective"))
    result["evidence_changed"] = canonical(before.get("evidence", [])) != canonical(new.get("evidence", []))
    result["hints_changed"] = canonical(before.get("hints", {})) != canonical(new.get("hints", {}))
    result["unchanged"] = old is not None and canonical(old) == canonical(new)
    return result


def evidence_for(raw: Mapping[str, object], constraint: Constraint) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for entry in _records(raw.get("evidence")):
        target = entry.get("target")
        fields: Mapping[str, object] = target if isinstance(target, Mapping) else {}
        if fields.get("constraint") == constraint.id or fields.get("param") in constraint.params:
            found.append(
                {
                    key: entry[key]
                    for key in ("target", "source", "date", "quote", "confidence", "inputs")
                    if key in entry
                }
            )
    return found


def rests_on_assumption(raw: Mapping[str, object], constraint: Constraint) -> bool:
    evidence = evidence_for(raw, constraint)
    if constraint.category == "assumption" or any(entry.get("confidence") == "assumption" for entry in evidence):
        return True
    backed = {
        fields.get("param")
        for entry in evidence
        if isinstance(fields := entry.get("target"), Mapping) and fields.get("param") is not None
    }
    unbacked_param = any(param not in backed for param in constraint.params)
    return unbacked_param or (constraint.category == "fact" and len(evidence) == 0)
