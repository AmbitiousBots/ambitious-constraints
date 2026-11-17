---
name: verify-module-formal
description: Model-check this Ambitious module's behavior where the order of steps matters (state changes, retries, concurrent runs) with TLA+ and the TLC model checker. Use when a change touches code listed in the coverage table below or any file under spec/.
---

# Formal verification of this module

A test checks the cases someone wrote. A model check tries every order of steps in a small model of the design. Use it for behavior a person relies on that has ordering, retries, concurrency or a state machine.

One command checks every model:

```text
npm run tlc
```

It needs the pinned tools (`mise trust && mise install`): Java, and `tla2tools.jar`, the TLA+ tools, pinned by address and SHA-256 in `.mise.toml`. It prints a table and exits non-zero when a model fails or a broken variant is not caught. `spec/README.md` explains the files.

## What is covered

Last confirmed in step with the code at the commit that added `spec/ModelCommit.tla`. Move this forward only after you have read the covered code at the new commit and confirmed that the model still describes it.

| Model | Covers | Each model step is this code |
|---|---|---|
| `spec/ModelCommit.tla` | `commit` and `clone` in `src/ambitious_constraints/cli/main.py` with `commit_model`, `clone_model` and `with_receipt` in `src/ambitious_constraints/db/store.py` | `Propose`: `model propose`, which reads the stored version and writes nothing. `Commit`: one `model commit` transaction: the receipt lookup, the digest comparison (`sent = want[w]`), the `base_version` comparison (`base[w] = Version`), the insert of the new version and of the receipt. `RefuseStale`: the `E_STALE` failure, which stores nothing. `Replay`: a repeated request with the same `idem_key`, answered from the receipt. `NextRequest`: the caller choosing a new `idem_key`. `Clone`: one `model clone` transaction. |

One model step is one indivisible step in the code: every write command runs inside the single `BEGIN IMMEDIATE` transaction the kit wraps around it, so two commits never interleave.

## The properties, in plain words

| Invariant | Promise | Harm if it broke |
|---|---|---|
| `NoLostUpdate` | A commit succeeds only against the version it was prepared from. | A person approves a change, and it silently erases a change someone else stored a moment earlier. |
| `CommittedIsProposed` | What is stored is what was proposed and shown. | A person approves one model and a different one becomes the record. |
| `ReceiptNamesAStoredVersion` | A repeated request is answered with a version that exists. | A bot would report a version that was never stored. |
| `CloneIsTheNamedVersion` | A clone is the version its `forked_from` names. | A copy made to explore one version would start from another. |

Bounds and assumptions: two writers, two contents, three versions, one model and one clone. SQLite gives each write command an exclusive transaction. The model does not cover the solver or the analysis commands; those are read-only and are covered by the tests against brute force.

## Each property has been seen to fail

| Broken variant | Protection removed | Must break |
|---|---|---|
| `CommitIgnoresBaseVersion` | The comparison of `base_version` with the stored version | `NoLostUpdate` |
| `CommitWithoutDigest` | The comparison of the model with the proposed digest | `CommittedIsProposed` |
| `CloneCopiesLatest` | Copying the named version rather than the newest | `CloneIsTheNamedVersion` |

## When you change covered code

1. Decide whether the change alters a step in the table above: a new write, a different order, a new way to fail. If it does not, run `npm run tlc` and you are done.
2. If it does, change the model first so it describes the new design, run `npm run tlc`, then change the code to match.
3. If TLC reports a violation, read the numbered states it prints from top to bottom: each one is one step, and the last is where the rule broke. Retell the path in the code's terms.
4. Decide which is wrong. If the path can happen in the code, it is a real bug: fix the code, keep the property. If it cannot, fix the model so it matches the code, and say in the pull request what was wrong with it. Never weaken or delete an invariant to get a pass.
5. For a new protection, add a broken variant that removes only that protection, with its entry in `EXPECTED.json`.
