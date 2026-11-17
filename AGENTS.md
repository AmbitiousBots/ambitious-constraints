# Agent guide

## Goal

Ambitious is a Grok Bot configuration and monitoring service: a free Ambitious Bot template with a daily analysis that stays in the owner's account, the Ambitious Bot plan, $725/month per bot, for a person's review of each report, and open-source single-purpose CLI modules with no UI that the bot drives. This repo is one of those modules. The user is a person who talks to a bot and never sees this code, so a change is good when the bot can do more for them, or the same with less risk.

## How to work

- Work in small steps and prove each one: say what the change must do, make the smallest change that does it, then run the checks and show their output. Model choices per agent role are in `.cursor/rules/agent-models.mdc`. Claude Code analysis runs use `--model claude-fable-5-2`.
- Trust in this order: types and API design, then lint and the dependency graph, then tests and verification, then prose.
- When you are corrected, turn the correction into a lint rule with a fix-the-root-cause message or into an API change. Do not add it to this file.
- When a check fails, fix the cause. Never weaken or skip a check to make it pass.

## Data shape

- In: JSON on stdin or `--in`. Out: one JSON envelope on stdout, `{ ok, schemaVersion, module, command, data, errors, meta }`.
- State: one SQLite file. Its shape is the files in `src/ambitious_constraints/migrations/` plus the types in `src/ambitious_constraints/domain/model.py`. Read those before changing behavior; they are the source of truth, not this file.
- A model is a `constraint-model.v1` document and a solution a `constraint-solution.v1` document. The schemas under `src/ambitious_constraints/schemas/` are copies of the kit's; change them in ambitious-kit first, then refresh the copies and the checksums in `tests/test_schemas.py`.
- The full contract is [MODULE_CONTRACT.md](MODULE_CONTRACT.md), a copy of the one in the ambitious-kit repo.

## Directory boundaries

- `src/ambitious_constraints/cli/`: input parsing at the boundary and the envelope only. The one place that reads the environment; the kit runner there reads the clock and the seed.
- `src/ambitious_constraints/domain/`: pure logic with no IO: the model and its compiler (`model.py`), the checker that does not use the solver (`check.py`), conflict enumeration (`explain.py`) and the analyses (`analysis.py`), which reach the solver only through the `Engine` protocol.
- `src/ambitious_constraints/solver/`: the only place that imports `ortools`. It is imported lazily, after the pinned runtime is on the import path.
- `src/ambitious_constraints/db/`: the only place that imports `sqlite3`.
- `src/ambitious_constraints/migrations/`, `schemas/` and `runtime.txt`: package data: the forward-only migrations, the copies of the interchange schemas, and the runtime lock.
- `examples/`: models built as data. `tests/`: tests, with recorded results under `tests/fixtures/`. `spec/`: TLA+ models. `verify/`: the verification skill. `vendor/`: the kit, unpacked, and the kit installer.
- There is no network code anywhere in the module. The kit installer downloads the runtime.

## Judgment calls

- Which layer a piece of code belongs in: if it can be stated without IO, it is domain logic, even when it is first needed by a database or AI call.
- Whether a behavior needs a model in `spec/` before code: yes when it has ordering, retries, concurrency or a state machine a person relies on.
- What an error says: plain words a bot can relay, and a hint the bot can act on without a human.
- How much to build: the smallest change that meets the goal. Delete before you add.
- What counts as proof: output from `verify/run` against a fresh `AMBITIOUS_HOME`, not a reading of the diff.
- What to write down: a choice you made without asking goes in the PR under `## Decisions`.
- Whether a result is trustworthy: only when the independent checker agrees with the solver. A new constraint kind is not done until `check.py` evaluates it, the brute-force property tests generate it, and the solver and the checker are compared on it.
- What may change an answer: only the input, `--seed` and the runtime lock. Never add a clock limit, a second solver worker or a default that depends on the machine.
- Wording: keep code and docs generic for every kind of organization. No person, bot or customer names, no industry terms, and no compliance or security claim beyond what the code enforces.
