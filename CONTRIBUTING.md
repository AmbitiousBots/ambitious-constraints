# Contributing

Thank you for helping. This repository is an [Ambitious](https://ambitiousbots.com) module: an open-source, single-purpose command-line tool with no user interface. A bot runs it, passes JSON in and reads JSON out. The rules every module follows are in `MODULE_CONTRACT.md` in the [ambitious-kit](https://github.com/AmbitiousBots/ambitious-kit) repository, and [AGENTS.md](AGENTS.md) describes how this repository is laid out.

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## File an issue

- A bug: open an issue with the bug report form. Give the exact command, its input, everything it printed, and the versions the form asks for.
- An idea: open an issue with the feature request form before you write much code, so the approach can be agreed first.
- A security vulnerability: do not open an issue. Follow [SECURITY.md](SECURITY.md).

Replace real keys, passwords and personal data with made-up values in anything you post.

## Set up a checkout

You need two tools:

- [git](https://git-scm.com).
- [mise](https://mise.jdx.dev), a tool-version manager. It installs the exact Node, Python and Java versions pinned in `.mise.toml`, so you do not install those yourself. Node runs the code and the checks, Python is for modules written in Python, and Java runs TLC, the TLA+ model checker.

Then, in your clone:

```text
mise trust && mise install
python3 -m pip install --require-hashes --only-binary :all: -r scripts/dev-requirements.txt
npm run runtime
```

The second line installs the two lint tools, mypy and ruff, at pinned versions; use a virtual environment and set `PY` to its Python if you prefer. The third builds the module and installs it, with the pinned solver runtime, into `.build/home` through the kit installer in `vendor/`. It downloads the locked packages once. There is no `npm ci`: the repository has no Node dependencies.

## Run the checks

Run every check before you push:

| Command | What it checks |
|---|---|
| `npm run typecheck` | mypy in strict mode on the module, the scripts and the examples. |
| `npm run lint` | No code comments, the ruff rules (no clock, randomness, network or database access outside the directory that owns it), and that no tracked file contains an internal plan ID or a path on one person's machine. |
| `npm run test` | The unit, property and regression tests. They solve with the runtime in `.build/home`. |
| `npm run contract` | The kit's contract tests against the built `.pyz`, in a fresh home with no runtime. |
| `npm run tlc` | Every TLA+ model in `spec/` passes the TLC model checker, and every deliberately broken copy in `spec/broken/` breaks the rule listed for it. |
| `npm run verify` | `verify/run`: every feature in `verify/features.json`, each against a fresh temporary `AMBITIOUS_HOME` (the directory a module keeps its data in). |

`npm run release:check` runs them all in that order. A check that fails means the change is not ready. Fix the cause; never weaken or skip the check.

A change to what a model or a solution looks like is a change to an interchange schema. Make it in [ambitious-kit](https://github.com/AmbitiousBots/ambitious-kit) first, then refresh the copies under `src/ambitious_constraints/schemas/` and their checksums in `tests/test_schemas.py`.

To change the runtime lock, regenerate `src/ambitious_constraints/runtime.txt` with one exact version per package and the SHA-256 of every wheel for Python 3.13 on Linux x86-64, Linux arm64 and macOS arm64, re-run every regression test, and update `NOTICE`. A new lock is a new runtime directory, so existing installs are not touched.

## Open a pull request

1. Fork the repository, or create a branch if you have write access. Keep one purpose per pull request.
2. Make the smallest change that meets the goal. When behavior changes, change the tests with it, and add or update the entry in `verify/features.json` for anything a user can see.
3. Write commit messages and the pull request in plain language. Everything in this repository is public, so write nothing that only makes sense inside one organisation: no private ticket numbers, no paths on your machine, no names of people or customers.
4. Fill in every section of the pull request template: why, what changed, evidence (paste the output of `verify/run`), and the decisions you made on your own.
5. A maintainer reviews the pull request and merges it once the checks pass.

## License

This repository is licensed under the Apache License, Version 2.0; see [LICENSE](LICENSE). As section 5 of the license says, anything you submit for inclusion is under the same license, with no additional terms.
