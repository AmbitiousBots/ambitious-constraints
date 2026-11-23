# ambitious-constraints

Ambitious Constraints is a command-line decision checker for bots. A bot states a decision as a model: variables, the numbers it depends on, the evidence behind each number, and constraints that are definitions, facts, policies, assumptions, goals or desires. The module stores versions of that model in SQLite and answers questions about it: is there a plan that satisfies everything, which is best, and when there is none, which smallest sets of constraints cannot all hold and what is the least that has to be given up. It also compares scenarios and sweeps an assumption to find where the answer changes. Every command reads JSON and returns one JSON envelope. There is no user interface, document rendering, network access or AI key.

Solving uses CP-SAT from [OR-Tools](https://developers.google.com/optimization), which is a native package and cannot live inside the module's single file. It is an opt-in, hash-pinned runtime that the kit installer builds only when asked. Without it the module still stores and validates models, and each solving command says what is missing.

Part of [Ambitious](https://ambitiousbots.com). The shared [module contract](MODULE_CONTRACT.md) defines the envelope, installation, database, the pinned runtime and how data crosses between modules.

## Install

A release has three files: `ambitious-constraints-0.1.2.pyz`, `ambitious-constraints-0.1.2.runtime.txt` (the runtime lock) and `SHA256SUMS`. The module needs Python 3.13. The runtime needs `python3 -m venv` to work (on Debian that is the `python3-venv` package) and, the first time, access to the Python package index.

```sh
node ambitious-install-0.4.9.mjs constraints 0.1.2 --kind pyz --runtime --from <release address or directory>
python3 "$AMBITIOUS_HOME/bin/ambitious-constraints" selfcheck
```

The installer verifies the `.pyz` and the lock against `SHA256SUMS`, then builds a Python environment that holds exactly the locked packages under `$AMBITIOUS_HOME/constraints/runtime/<SHA-256 of the lock>/`. `pip` checks every downloaded file against the hashes in the lock. A failed or interrupted build leaves nothing in place, and running the installer again changes nothing. Leave out `--runtime` to install only the module. The runtime is about 200 MB on disk; the module itself is under 100 KB.

`selfcheck` reports the runtime in `data.pinnedRuntime` (`state` is `ready`, `missing` or `damaged`) and says what to do in `data.warnings`. A missing runtime is a warning, not a problem: `selfcheck` stays `ok`.

`AMBITIOUS_HOME` defaults to `/workspace/ambitious`, the module storage directory on a Grok Bot computer. The database is `$AMBITIOUS_HOME/constraints/constraints.sqlite`; `--db` overrides that file. Modules refuse `/home/box/agent-data`, the bot's private data directory.

### From a checkout, on a computer with no root access

This is the whole procedure on Debian 13 with the distribution's Python 3.13 and Node 24. Nothing is installed outside the checkout and `AMBITIOUS_HOME`.

```sh
git clone https://github.com/AmbitiousBots/ambitious-constraints.git && cd ambitious-constraints
export AMBITIOUS_HOME="$HOME/ambitious"
node scripts/runtime.mjs "$AMBITIOUS_HOME"
python3 "$AMBITIOUS_HOME/bin/ambitious-constraints" selfcheck
```

`scripts/runtime.mjs` builds the release files into `dist/` and runs the kit installer from `vendor/` with `--runtime`, exactly as above. To run the tests there:

```sh
node scripts/runtime.mjs
node scripts/py.mjs -m unittest discover -s tests -t .
node scripts/py.mjs -m ambitious_kit.contract dist/ambitious-constraints.pyz
node verify/run --only contract --only install-and-decide --only without-the-runtime --only write-rules --only analysis --only pricing-regression --only planning-regression --only checked-against-brute-force --only time-slots --only interchange-schemas
```

The first line installs the runtime into `.build/home`, where the tests look for it. The tests use only the standard library. `node verify/run` with no arguments also checks the TLA+ models, which needs the Java pinned in `.mise.toml`.

## JSON interface

```text
ambitious-constraints <command> [--in input.json] [--db constraints.sqlite] [--now ISO8601] [--seed integer] [--json] [--help]
```

Pass one JSON object on stdin or with `--in`, never both. Every response is one line, `{ ok, schemaVersion, module, command, data, errors, meta }`. Successful commands exit 0, caller errors exit 1, database and internal failures exit 2. `--help`, with or without a command name, answers with the same listing as `commands` and does not run the command.

| Command | Access | Needs the runtime | Input | Result in `data` |
|---|---|---|---|---|
| `commands` | none | no | none | `commands` with names, access and input requirements |
| `selfcheck` | write | no | none | runtime, binary SHA-256, database integrity, applied migrations, `problems`, `pinnedRuntime`, `warnings` |
| `model validate` | none | no | `{model}` | `valid`, `digest`, `problems`, `counts` |
| `model propose` | read | no | `{model, model_id?}` | the same report, plus `base_version` (the stored version, 0 when new), `diff` against the stored version and `stored: false`. Nothing is written. |
| `model commit` | write | no | `{model_id, base_version, digest, model, idem_key, actor}` | `model_id`, `version`, `digest`, `replayed` |
| `model clone` | write | no | `{model_id, version?, new_id, idem_key, actor}` | `model_id` (the new one), `version: 1`, `digest`, `forked_from`, `replayed` |
| `model get` | read | no | `{model_id, version?}` | `model`, `version`, `latest_version`, `digest`, `forked_from`, `actor`, `at` |
| `model history` | read | no | `{model_id}` | ordered `events` |
| `model list` | read | no | none | `models` |
| `solve` | read | yes | `{model_id, version?}` or `{model}`, with `scenario?`, `limits?` | `solution`, a `constraint-solution.v1` document |
| `explain` | read | yes | the same, with `max_sets?: 20`, `max_depth?: 6` | `status`, `mus`, `mcs`, `levers`, `rests_on_assumptions`, `complete`, `structural_conflict` |
| `whatif` | read | yes | `{model_id \| model, scenarios: [name \| {name, overrides}], base?: true, limits?}` | `scenarios`, one solution per scenario in `results`, and `differences`: the variables whose values differ |
| `sweep` | read | yes | `{model_id \| model, scenario?, param, grid: [integers], limits?}` | `points` with status, objective and values, and `flips`: where feasibility changes |
| `run record` | write | no | `{envelope, idem_key, actor, note?}` | `run_id`, `recorded`, `at`, `replayed` |
| `run get` | read | no | `{run_id}` | the stored `envelope` and its summary |
| `run list` | read | no | `{model_id?}` | `runs` |

Reads open SQLite read-only and cannot create or migrate a database: run `selfcheck` first if a read reports `E_MIGRATION`. The analysis commands are reads even with a stored `model_id`. To keep a result, pass the whole envelope a command printed to `run record`.

`limits` is `{ "deterministic_time": 10 }`, a whole number from 1 to 600. It is the solver's own deterministic work measure, not seconds; on a laptop one unit is on the order of a second.

### Writing follows three rules

- **A proposal writes nothing.** `model propose` returns the `digest` of the model, the `base_version` it was compared with, and the difference. Show that to the person.
- **A commit changes one model, from one version.** `model commit` names the `model_id`, the `base_version` the proposal reported and the `digest`. It stores version `base_version + 1`. If the model moved on in the meantime the commit fails with `E_STALE` and stores nothing; if the model sent is not the one proposed it fails with `E_DIGEST`.
- **A copy is always explicit.** `model clone` copies one version to a new id and records `forked_from`. No write ever creates a branch on its own.

Every write takes an `idem_key`. Repeating a request with the same key returns the first answer with `replayed: true` and changes nothing; a different request under a used key fails with `E_IDEM_CONFLICT`. Stored model versions, the event history and recorded runs cannot be updated or deleted: the database refuses it.

## The model

A model is a [`constraint-model.v1`](src/ambitious_constraints/schemas/constraint-model.v1.json) document, one of the interchange schemas the kit publishes. [`tests/fixtures/two-offers.json`](tests/fixtures/two-offers.json) is a small complete one.

Every number is an integer. Scale a quantity that has a fraction (cents, hundredths of an hour) and say so in the parameter's `scale` or `unit`.

- **Variables.** `bool`; `int` with a domain of `{lo, hi}`, `{values: [...]}` or `{ranges: [[lo, hi], ...]}`; `enum` with `{values: [names]}`; `interval` with `{start, size, end, present?}`, where `start` and `end` name `int` variables and `present` is a literal that says whether the interval exists.
- **Literals.** `x`, `!x`, `mode=fast`, `!mode=fast`.
- **Parameters.** Named integers. Anywhere a number is expected, `"param:name"` or `"-param:name"` stands for the parameter's value, so a scenario or a sweep can change it in one place.
- **Constraints.** Each has an `id`, a `kind`, `args`, and a `strength`:
  - `structural`: a definition. Always enforced, never part of a conflict.
  - `hard`: must hold. It can appear in a conflict set.
  - `soft`: may be broken at a cost of `weight` in the objective.
- **Category and levers.** `category` is `desire`, `goal`, `policy`, `fact`, `assumption` or `definition`. The levers, the constraints `explain` will propose to give up, are the hard constraints with category `desire` or `goal` that are not marked `negotiable: false`. Facts, policies and assumptions are never offered for removal.
- **Evidence.** Each entry targets a constraint or a parameter and states its `source` and its `confidence`: `sourced`, `derived` (name the `inputs`) or `assumption`. A fact, assumption or parameter with no evidence is reported by `model validate` as a warning and treated as an assumption.
- **Objective.** `{sense: "max" | "min", terms: [{coef, var}]}` or `null`. Soft penalties are subtracted from a maximum and added to a minimum.
- **Scenarios.** Named `overrides`: `disable` ids, set `params`, `soften` ids to a weight, `harden` ids, `add` constraints.
- **Hints.** `{variable: value}`, a starting assignment. The solver tries it first, so a hinted feasible plan is never made worse.

| Kind | `args` | Notes |
|---|---|---|
| `linear` | `{terms: [[coef, var], ...], op: "<=" \| ">=" \| "==" \| "!=", rhs, if?: [literals]}` | A term's variable is an `int`, a `bool` or `name=value`. |
| `implication` | `{if: [literals], then: [literals], all?: false}` | When every `if` literal holds, one `then` literal holds, or all of them with `all: true`. |
| `exactly_one`, `at_most_one` | `{lits: [literals], if?}` | |
| `fix` | `{lit}` or `{var, value}` | |
| `product` | `{target, factors: [a, b]}` | Structural only. |
| `element` | `{index, values: [numbers], target}` | `target` is `values[index]`. Structural only. |
| `precedence` | `{before, after, gap?: 0, if?}` | The interval `before` ends, plus `gap`, no later than `after` starts. |
| `no_overlap` | `{intervals: [names]}` | Structural only. Intervals of size 0 are refused. |
| `cumulative` | `{intervals, demands: [numbers], capacity}` | Structural only. |

Any kind may give `args` as `{rows: [...]}` to group several rows under one id, so they stand or fall together in a conflict set; a row may name its own `kind`.

A model may have at most 20,000 variables, 50,000 constraints and 200,000 rows. `model validate` reports a larger one as a problem.

### Placing blocks of time

Use minutes (or any whole unit) from the start of the horizon. Give each block an `interval` with a fixed `size`, put the blocks of one calendar in one `no_overlap`, order dependent blocks with `precedence`, and bound them with a `makespan` variable (`end - makespan <= 0`, minimize `makespan`). There are two ways to say when work may happen, and they give the same answers:

- as the start variable's `ranges`, one `[first start, last start]` pair per free window; or
- as fixed intervals for the closed hours (a start variable whose domain is a single value), added to the calendar's `no_overlap`.

With many windows the second is far faster: a plan of about 600 blocks over 600 days solved in about 5 seconds with blocking intervals and took over a minute with range domains, because the solver's preparation step is slow on variables with hundreds of ranges. Pass the schedule you already have as `hints`.

## What the answers mean

`solve` returns [`constraint-solution.v1`](src/ambitious_constraints/schemas/constraint-solution.v1.json):

- `status` is what was proved. `optimal`: no better plan exists. `feasible`: a plan, but the search stopped at its limit, so a better one may exist; `bound` is the best the objective could still be. `infeasible`: no plan exists. `unknown`: the limit was reached first. Never report `feasible` as the best plan.
- `values` holds every variable: booleans as `true`/`false`, enums by name.
- `soft_violated` lists the soft constraints the plan gives up, with their weights.
- `checked.violations` comes from a second implementation that does not use the solver: it re-evaluates every constraint on the returned values and recomputes the objective. It is empty unless the solver and the checker disagree, which is a bug to report.
- `rests_on_assumptions` lists the hard and soft constraints whose own evidence, or the evidence of a parameter they use, is an assumption or is missing. A result with a non-empty list holds only as far as those assumptions do. Say so whenever you relay it.
- `solver` records the solver version, the seed it used, the single worker, the limit and the SHA-256 of the runtime lock.

`explain` works on the hard constraints:

- `mus`: minimal conflict sets. Each is a set of hard constraints that cannot all hold, and removing any one member makes the rest satisfiable. Each member carries its `label`, `category`, whether it is a `lever`, its strongest evidence `confidence` and whether it `rests_on_assumption`.
- `mcs`: minimal correction sets, smallest first. Each is a set of levers whose removal makes the model feasible, and no smaller part of it does.
- `complete` is `false` when `max_sets` or `max_depth` stopped the search early, so more sets may exist. `structural_conflict` is `true` when the definitions alone contradict each other.
- When a subproblem cannot be decided within the limit, `explain` and `sweep` fail with `E_LIMIT` instead of guessing.

## Determinism

The solver runs with one worker, a seed derived from `--seed`, and a deterministic work limit; it is never given a clock limit. Variables and constraints are built in sorted order, and nothing in a result comes from the clock: `--now` is used only as the time of a write. The same binary, runtime, database state, input and `--seed` print the same bytes, on any day. The tests check this for every analysis command.

## Error codes

Shared codes are in the [module contract](MODULE_CONTRACT.md). `E_RUNTIME` (exit 1) is the shared code for a solving command run without the pinned runtime. The module's own:

| Code | Exit | Meaning | Typical hint |
|---|---|---|---|
| `E_MODEL` | 1 | The model matches the schema but has problems: an unknown variable or parameter, a kind that can only be structural, a duplicate id. `data.problems` lists every one. | Run `model validate` and fix each problem with severity `error`. |
| `E_STALE` | 1 | `model commit` named a `base_version` that is no longer the stored version. Nothing was stored. | Propose against the current version, show the difference, commit with the new `base_version`. |
| `E_DIGEST` | 1 | The model sent to `model commit` is not the one whose digest was given. | Commit exactly the model that `model propose` showed. |
| `E_IDEM_CONFLICT` | 1 | The `idem_key` was already used for a different request. | Retry with exactly the first request, or use a new key for a new action. |
| `E_EXISTS` | 1 | `model clone` named a `new_id` that is already a model. | Choose an id that is not in use. |
| `E_NOT_FOUND` | 1 | The model, version, scenario, parameter or run does not exist. | Use `model list`, `model history` or `run list`. |
| `E_LIMIT` | 1 | The solver could not decide within `limits.deterministic_time`. | Raise the limit or make the model smaller. |

## Examples and regression data

- [`examples/pricing`](examples/pricing) builds a pricing model as data: a price table and a demand table (`element`), revenue (`product`), two capacity limits and an objective. `node scripts/py.mjs examples/pricing/build_model.py --mode profit` prints a `solve` input. The tests reproduce the 288 optimal plans, the 5% price ranges, 616 fixed-price points and 12 break-even searches that an earlier prototype recorded with the same solver version.
- [`tests/fixtures/planning-regression.json`](tests/fixtures/planning-regression.json) is that prototype's planning model with neutral identifiers, and the results it recorded for 11 scenarios. The tests reproduce every status and optimum and the same correction sets, and confirm every recorded conflict set is minimal.

## Verification

```text
mise trust && mise install
python3 -m pip install --require-hashes --only-binary :all: -r scripts/dev-requirements.txt
npm run release:check
```

`release:check` runs the type check (mypy strict), the lint rules including the comment ban, the tests, the kit's contract tests on the built `.pyz`, the TLA+ models and `verify/run`. [`spec/ModelCommit.tla`](spec/ModelCommit.tla) models propose, commit, replay and clone with two writers; three broken copies show that the model catches a commit that ignores `base_version`, a commit that ignores the digest, and a clone that copies the wrong version.

Licensed under the Apache License, Version 2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). The runtime packages are downloaded by the installer and are not part of this repository or its releases; `NOTICE` lists them and their licenses.
