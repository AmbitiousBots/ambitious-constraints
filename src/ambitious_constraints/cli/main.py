from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.resources import files

from ambitious_kit.cli.command import Context, DbContext, no_input, pure_command, read_command, write_command
from ambitious_kit.cli.runner import ModuleSpec, run_cli
from ambitious_kit.db.sqlite import load_migrations
from ambitious_kit.domain.clock import format_instant
from ambitious_kit.domain.envelope import JsonObject, envelope_problems, failure
from ambitious_kit.domain.json_schema import schema_problems
from ambitious_kit.runtime import activate, lock_sha256, pinned_runtime, runtime_failure

from ambitious_constraints import MODULE, VERSION
from ambitious_constraints.db import store
from ambitious_constraints.domain import analysis, requests
from ambitious_constraints.domain.explain import Oracle
from ambitious_constraints.domain.jsonio import json_object
from ambitious_constraints.domain.model import (
    MODEL_SCHEMA,
    Compiled,
    Problem,
    diff_models,
    digest_of,
    semantic_problems,
)

PACKAGE = files("ambitious_constraints")
RUNTIME_LOCK = (PACKAGE / "runtime.txt").read_text(encoding="utf-8")
MODEL_SCHEMA_DOCUMENT: object = json.loads(
    (PACKAGE / "schemas" / "constraint-model.v1.json").read_text(encoding="utf-8")
)


class CpSatEngine:
    def __init__(self, env: Mapping[str, str]) -> None:
        runtime = pinned_runtime(env, MODULE, RUNTIME_LOCK)
        activate(runtime)
        try:
            from ambitious_constraints.solver import cpsat
        except ImportError as error:
            raise runtime_failure(runtime) from error
        self.cpsat = cpsat

    def version(self) -> str:
        return self.cpsat.solver_version()

    def lock_sha256(self) -> str:
        return lock_sha256(RUNTIME_LOCK)

    def solve(self, model: Compiled, seed: int, deterministic_time: int) -> analysis.Outcome:
        return self.cpsat.solve(model, seed, deterministic_time)

    def oracle(self, model: Compiled, seed: int, deterministic_time: int) -> Oracle:
        return self.cpsat.ConflictOracle(model, seed, deterministic_time)


def _problems(model: Mapping[str, object]) -> list[Problem]:
    shape = [
        Problem("error", "SCHEMA", found.pointer or "/", f"{found.pointer or '/'} {found.keyword}: {found.message}")
        for found in schema_problems(MODEL_SCHEMA_DOCUMENT, model)
    ]
    return shape if shape else list(semantic_problems(model))


def _report(model: Mapping[str, object]) -> dict[str, object]:
    problems = _problems(model)
    counted = {
        name: len(value) if isinstance(value := model.get(name), list) else 0
        for name in ("variables", "params", "constraints", "evidence", "scenarios")
    }
    return {
        "valid": not any(problem.severity == "error" for problem in problems),
        "digest": digest_of(model),
        "problems": [problem.to_json() for problem in problems],
        "counts": counted,
    }


def _loose_model(raw: object, allowed: tuple[str, ...]) -> tuple[Mapping[str, object], Mapping[str, object]]:
    fields = requests.record(raw, allowed)
    model = fields.get("model")
    if not isinstance(model, dict):
        raise requests.invalid(f'The field "model" must be a {MODEL_SCHEMA} document.')
    return fields, model


@dataclass(frozen=True)
class Proposal:
    model: Mapping[str, object]
    model_id: str | None


def parse_validate(raw: object) -> Mapping[str, object]:
    return _loose_model(raw, ("model",))[1]


def validate(context: Context[Mapping[str, object]]) -> JsonObject:
    return json_object(_report(context.input))


def parse_propose(raw: object) -> Proposal:
    fields, model = _loose_model(raw, ("model", "model_id"))
    return Proposal(model, None if fields.get("model_id") is None else requests.model_id(fields))


def propose(context: DbContext[Proposal]) -> JsonObject:
    request = context.input
    report = _report(request.model)
    stored = None if request.model_id is None else store.find_model(context.db, request.model_id)
    base_version = 0 if stored is None else stored.latest
    return json_object(
        {
            **report,
            "model_id": request.model_id,
            "base_version": base_version,
            "diff": diff_models(None if stored is None else stored.doc, request.model),
            "stored": False,
        }
    )


@dataclass(frozen=True)
class Commit:
    model_id: str
    base_version: int
    digest: str
    model: Mapping[str, object]
    idem_key: str
    actor: str


def parse_commit(raw: object) -> Commit:
    fields = requests.record(raw, ("model_id", "base_version", "digest", "model", "idem_key", "actor"))
    return Commit(
        requests.model_id(fields),
        requests.whole(fields, "base_version", 0, 2**31),
        requests.sha256(fields, "digest"),
        requests.model_document(fields, MODEL_SCHEMA_DOCUMENT),
        requests.text(fields, "idem_key"),
        requests.text(fields, "actor"),
    )


def commit(context: DbContext[Commit]) -> JsonObject:
    request = context.input
    at = format_instant(context.now)

    def act() -> dict[str, object]:
        actual = digest_of(request.model)
        if actual != request.digest:
            raise failure(
                "E_DIGEST",
                f"The model sent has digest {actual}, but the commit names {request.digest}.",
                "Commit exactly the model that model propose showed, with the digest it returned.",
                {"digest": actual},
            )
        problems = _problems(request.model)
        if any(problem.severity == "error" for problem in problems):
            raise failure(
                "E_MODEL",
                "The model has problems, so it was not stored.",
                "Run model validate, fix every problem with severity error, then propose and commit again.",
                {"problems": [problem.to_json() for problem in problems]},
            )
        return store.commit_model(
            context.db,
            model_id=request.model_id,
            base_version=request.base_version,
            digest=actual,
            doc=request.model,
            actor=request.actor,
            at=at,
            idem_key=request.idem_key,
        )

    described = {
        "command": "model commit",
        "model_id": request.model_id,
        "base_version": request.base_version,
        "digest": request.digest,
        "actor": request.actor,
    }
    return json_object(store.with_receipt(context.db, request.idem_key, described, act))


@dataclass(frozen=True)
class Clone:
    model_id: str
    version: int | None
    new_id: str
    idem_key: str
    actor: str


def parse_clone(raw: object) -> Clone:
    fields = requests.record(raw, ("model_id", "version", "new_id", "idem_key", "actor"))
    return Clone(
        requests.model_id(fields),
        requests.optional_whole(fields, "version", 1, 2**31),
        requests.model_id(fields, "new_id"),
        requests.text(fields, "idem_key"),
        requests.text(fields, "actor"),
    )


def clone(context: DbContext[Clone]) -> JsonObject:
    request = context.input
    described = {
        "command": "model clone",
        "model_id": request.model_id,
        "version": request.version,
        "new_id": request.new_id,
        "actor": request.actor,
    }

    def act() -> dict[str, object]:
        source = store.get_model(context.db, request.model_id, request.version)
        return store.clone_model(
            context.db,
            source=source,
            new_id=request.new_id,
            actor=request.actor,
            at=format_instant(context.now),
            idem_key=request.idem_key,
        )

    return json_object(store.with_receipt(context.db, request.idem_key, described, act))


@dataclass(frozen=True)
class Lookup:
    model_id: str
    version: int | None


def parse_lookup(raw: object) -> Lookup:
    fields = requests.record(raw, ("model_id", "version"))
    return Lookup(requests.model_id(fields), requests.optional_whole(fields, "version", 1, 2**31))


def parse_model_id(raw: object) -> str:
    return requests.model_id(requests.record(raw, ("model_id",)))


def get(context: DbContext[Lookup]) -> JsonObject:
    return json_object(store.get_model(context.db, context.input.model_id, context.input.version).to_json())


def history(context: DbContext[str]) -> JsonObject:
    return json_object({"model_id": context.input, "events": store.model_history(context.db, context.input)})


def list_models(context: DbContext[None]) -> JsonObject:
    return json_object({"models": store.list_models(context.db)})


@dataclass(frozen=True)
class Analysis:
    source: requests.Source
    scenario: str | None
    deterministic_time: int
    max_sets: int
    max_depth: int
    scenarios: tuple[tuple[str | None, Mapping[str, object] | None], ...]
    param: str
    grid: tuple[int, ...]


SHARED = ("model", "model_id", "version", "limits")


def _analysis(raw: object, extra: tuple[str, ...]) -> tuple[Mapping[str, object], Analysis]:
    fields = requests.record(raw, SHARED + extra)
    scenario = requests.optional_text(fields, "scenario") if "scenario" in extra else None
    return fields, Analysis(
        requests.source(fields, MODEL_SCHEMA_DOCUMENT),
        scenario,
        requests.deterministic_time(fields),
        requests.whole(fields, "max_sets", 1, requests.MAX_SETS, requests.DEFAULT_MAX_SETS),
        requests.whole(fields, "max_depth", 1, 12, requests.DEFAULT_MAX_DEPTH),
        (),
        "",
        (),
    )


def parse_solve(raw: object) -> Analysis:
    return _analysis(raw, ("scenario",))[1]


def parse_explain(raw: object) -> Analysis:
    return _analysis(raw, ("scenario", "max_sets", "max_depth"))[1]


def parse_whatif(raw: object) -> Analysis:
    fields, request = _analysis(raw, ("scenarios", "base"))
    listed = fields.get("scenarios")
    if not isinstance(listed, list) or not 1 <= len(listed) <= requests.MAX_SCENARIOS:
        raise requests.invalid(
            f'The field "scenarios" must be a list of 1 to {requests.MAX_SCENARIOS} scenario names '
            "or { name, overrides } objects."
        )
    chosen: list[tuple[str | None, Mapping[str, object] | None]] = [] if fields.get("base") is False else [(None, None)]
    for entry in listed:
        if isinstance(entry, str) and entry != "":
            chosen.append((entry, None))
        elif isinstance(entry, dict):
            inline = requests.record(entry, ("name", "overrides"))
            overrides = inline.get("overrides")
            if not isinstance(overrides, dict):
                raise requests.invalid(
                    'An inline scenario needs "overrides": an object with disable, params, soften, harden or add.'
                )
            unknown = sorted(set(overrides) - {"disable", "params", "soften", "harden", "add"})
            if unknown:
                raise requests.invalid(f'An inline scenario\'s overrides has the unexpected field "{unknown[0]}".')
            chosen.append((requests.text(inline, "name"), overrides))
        else:
            raise requests.invalid('Each entry of "scenarios" must be a scenario name or a { name, overrides } object.')
    return Analysis(request.source, None, request.deterministic_time, 1, 1, tuple(chosen), "", ())


def parse_sweep(raw: object) -> Analysis:
    fields, request = _analysis(raw, ("scenario", "param", "grid"))
    grid = fields.get("grid")
    if not isinstance(grid, list) or not 1 <= len(grid) <= requests.MAX_GRID:
        raise requests.invalid(f'The field "grid" must be a list of 1 to {requests.MAX_GRID} whole numbers.')
    points = [value for value in grid if isinstance(value, int) and not isinstance(value, bool)]
    if len(points) != len(grid):
        raise requests.invalid(
            'Every entry of "grid" must be a whole number. Scale a fraction and say so in the parameter\'s scale.'
        )
    return Analysis(
        request.source,
        request.scenario,
        request.deterministic_time,
        1,
        1,
        (),
        requests.text(fields, "param"),
        tuple(points),
    )


def _loaded(db: sqlite3.Connection, source: requests.Source) -> tuple[Mapping[str, object], dict[str, object]]:
    if source.model is not None:
        name = source.model.get("name")
        return source.model, {"name": name if isinstance(name, str) else "", "digest": digest_of(source.model)}
    stored = store.get_model(db, source.model_id or "", source.version)
    return stored.doc, stored.reference()


def _run(context: DbContext[Analysis]) -> analysis.Run:
    return analysis.Run(CpSatEngine(context.env), context.rng.getrandbits(31), context.input.deterministic_time)


def _analyse(
    work: Callable[[Mapping[str, object], dict[str, object], Analysis, analysis.Run], dict[str, object]],
) -> Callable[[DbContext[Analysis]], JsonObject]:
    def run(context: DbContext[Analysis]) -> JsonObject:
        raw, reference = _loaded(context.db, context.input.source)
        return json_object(work(raw, reference, context.input, _run(context)))

    return run


def _solve(
    raw: Mapping[str, object], reference: dict[str, object], request: Analysis, run: analysis.Run
) -> dict[str, object]:
    return {"solution": analysis.solution(raw, reference, request.scenario, run)}


def _explain(
    raw: Mapping[str, object], reference: dict[str, object], request: Analysis, run: analysis.Run
) -> dict[str, object]:
    return analysis.explain(raw, reference, request.scenario, run, request.max_sets, request.max_depth)


def _whatif(
    raw: Mapping[str, object], reference: dict[str, object], request: Analysis, run: analysis.Run
) -> dict[str, object]:
    return analysis.whatif(raw, reference, request.scenarios, run)


def _sweep(
    raw: Mapping[str, object], reference: dict[str, object], request: Analysis, run: analysis.Run
) -> dict[str, object]:
    return analysis.sweep(raw, reference, request.scenario, request.param, request.grid, run)


@dataclass(frozen=True)
class RunRecord:
    envelope: Mapping[str, object]
    command: str
    reference: Mapping[str, object]
    seed: int
    module_version: str
    idem_key: str
    actor: str
    note: str | None


def parse_run_record(raw: object) -> RunRecord:
    fields = requests.record(raw, ("envelope", "idem_key", "actor", "note"))
    envelope = fields.get("envelope")
    if not isinstance(envelope, dict) or envelope_problems(envelope):
        raise requests.invalid(
            'The field "envelope" must be the whole envelope that solve, explain, whatif or sweep printed.'
        )
    command, data, meta = envelope.get("command"), envelope.get("data"), envelope.get("meta")
    if envelope.get("ok") is not True or envelope.get("module") != MODULE or command not in requests.RUN_COMMANDS:
        raise requests.invalid(
            "Only a successful envelope from this module's solve, explain, whatif or sweep can be recorded.",
            "Pass the envelope exactly as the command printed it.",
        )
    holder = data.get("solution") if isinstance(data, dict) and command == "solve" else data
    reference = holder.get("model") if isinstance(holder, dict) else None
    if not isinstance(reference, dict) or not isinstance(reference.get("digest"), str) or not isinstance(meta, dict):
        raise requests.invalid("The envelope does not name the model it was computed from.")
    seed, version = meta.get("seed"), meta.get("version")
    return RunRecord(
        envelope,
        str(command),
        reference,
        seed if isinstance(seed, int) else 0,
        version if isinstance(version, str) else "",
        requests.text(fields, "idem_key"),
        requests.text(fields, "actor"),
        requests.optional_text(fields, "note"),
    )


def run_record(context: DbContext[RunRecord]) -> JsonObject:
    request = context.input
    run_id = f"run-{digest_of(request.envelope)[:16]}"
    described = {"command": "run record", "run_id": run_id, "actor": request.actor, "note": request.note}
    model_id, model_version = request.reference.get("id"), request.reference.get("version")

    def act() -> dict[str, object]:
        return store.record_run(
            context.db,
            run_id=run_id,
            at=format_instant(context.now),
            actor=request.actor,
            command=request.command,
            model_id=model_id if isinstance(model_id, str) else None,
            model_version=model_version if isinstance(model_version, int) else None,
            model_digest=str(request.reference.get("digest")),
            seed=request.seed,
            module_version=request.module_version,
            note=request.note,
            envelope=request.envelope,
            idem_key=request.idem_key,
        )

    return json_object(store.with_receipt(context.db, request.idem_key, described, act))


def parse_run_id(raw: object) -> str:
    fields = requests.record(raw, ("run_id",))
    return requests.text(fields, "run_id")


def run_get(context: DbContext[str]) -> JsonObject:
    return json_object(store.get_run(context.db, context.input))


def parse_run_list(raw: object) -> str | None:
    fields = requests.record(raw, ("model_id",))
    return None if fields.get("model_id") is None else requests.model_id(fields)


def run_list(context: DbContext[str | None]) -> JsonObject:
    return json_object({"runs": store.list_runs(context.db, context.input)})


def spec() -> ModuleSpec:
    return ModuleSpec(
        module=MODULE,
        version=VERSION,
        schema_version=1,
        migrations=load_migrations(PACKAGE / "migrations"),
        commands={
            "model validate": pure_command(validate, parse_validate),
            "model propose": read_command(propose, parse_propose),
            "model commit": write_command(commit, parse_commit),
            "model clone": write_command(clone, parse_clone),
            "model get": read_command(get, parse_lookup),
            "model history": read_command(history, parse_model_id),
            "model list": read_command(list_models, no_input),
            "solve": read_command(_analyse(_solve), parse_solve),
            "explain": read_command(_analyse(_explain), parse_explain),
            "whatif": read_command(_analyse(_whatif), parse_whatif),
            "sweep": read_command(_analyse(_sweep), parse_sweep),
            "run record": write_command(run_record, parse_run_record),
            "run get": read_command(run_get, parse_run_id),
            "run list": read_command(run_list, parse_run_list),
        },
        runtime_lock=RUNTIME_LOCK,
    )


def main() -> int:
    return run_cli(spec())
