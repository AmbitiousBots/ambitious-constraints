---
name: constraints-for-bots
description: Check a decision that has goals, limits and assumptions pulling against each other, with the Ambitious Constraints CLI. Use when a user asks whether a plan can satisfy everything they want, which option is best, why their goals cannot all hold, what is the least they would have to give up, or how much an assumption would have to change.
---

# Check decisions with Ambitious Constraints

Use the installed `ambitious-constraints` binary at `$AMBITIOUS_HOME/bin/ambitious-constraints`. When `AMBITIOUS_HOME` is not set, that path is `/workspace/ambitious/bin/ambitious-constraints`. Run `selfcheck --json` at routine start and read `data.problems` and `data.warnings`. Resolve a reported problem before writing data. Run `commands` to list the operations this binary offers. Read the module documentation at https://github.com/AmbitiousBots/ambitious-constraints#readme for the model format and every input shape.

Pass one JSON object on stdin or with `--in`, never both. Keep every input file outside `/home/box/agent-data`. You may pass `--json`; the module accepts it and changes nothing, because output is always JSON. When you need a repeatable result, pass `--now` and `--seed`, and keep the `now`, `seed` and `version` values from `meta` with the evidence.

Solving needs the module's pinned solver runtime, which is installed only when the owner asks for it. When `selfcheck` lists it under `data.warnings`, or a command answers `E_RUNTIME`, tell the owner that the runtime is not installed, that it is a download of about 200 MB, and that the module installer adds it with `--runtime`. Do not install it without the owner's yes. Storing, validating and showing models works without it.

Build the model with the person, not for them. Every number is a parameter with evidence: where it came from, and whether it is `sourced`, `derived` or an `assumption`. Never mark a guess as sourced. Give each constraint a plain `label` and the right `category`: what the person wants is a `desire` or a `goal`, what is true is a `fact`, what they will not bend is a `policy`, what nobody has checked is an `assumption`. Only desires and goals are offered as things to give up.

Writing follows three steps, in this order, every time:

1. `model propose` with the model and its `model_id`. It stores nothing. Fix every problem with severity `error`, and relay the warnings: each one is a number with no evidence.
2. Show the person the proposal and its `diff`. Wait for their yes.
3. `model commit` with the same model, the `base_version` and `digest` that propose returned, an `idem_key` and the `actor`. Choose one stable `idem_key` per intended action and keep it and the input unchanged for a retry. On `E_STALE` someone else changed the model: propose again and show the new difference; never retry with a higher `base_version` unseen. On `E_DIGEST` you are not committing what was shown: start again from propose.

To try a variant without touching the original, use `model clone` with a `new_id`. Never edit a model in place to explore.

Never compute a plan, a total, a conflict or a threshold by hand. Use `solve` for the best plan, `explain` when `solve` answers `infeasible`, `whatif` to compare scenarios side by side, and `sweep` to find the value of one assumption at which the answer changes.

When you relay a result:

- Say what was proved, in the module's word. `optimal` means no better plan exists. `feasible` means a plan was found and the search stopped at its limit, so a better one may exist: never call it the best. `unknown` means no answer yet: raise `limits.deterministic_time` or simplify the model.
- If `rests_on_assumptions` is not empty, say so before anything else and name those constraints by their labels. A result is only as sound as the assumptions it rests on.
- If `checked.violations` is not empty, do not use the result. Report it as a fault in the module.
- For `explain`, present each conflict set as "these cannot all hold" with the members' labels, and each correction set as "giving up these would make it possible". Mark members that rest on assumptions: checking such an assumption may dissolve the conflict without giving anything up. If `complete` is `false`, say more conflicts may exist.
- A recommendation to drop a goal is the person's decision. Offer the correction sets; do not pick one for them, and do not change the model until they choose.

To keep a result, pass the whole envelope the command printed to `run record` with an `idem_key`. The module does not render documents. If the user needs a readable document, write a Grok Bot Page from the JSON, or follow this module's Page skill.

Read the envelope and the exit code after every command. Require the expected `module` and `command`, a successful exit, and `ok: true` before using a result. When `ok` is false, relay `errors[].message`, `errors[].hint`, and `data.problems[]` when present, in plain words. Do not invent a successful result, and do not treat stderr logs as results. Never place credentials or private bot files in module input.
