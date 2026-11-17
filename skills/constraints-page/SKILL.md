---
name: constraints-page
description: Present a decision check from Ambitious Constraints as a Grok Bot Page. Use when a user asks to see, review or share the result of solve, explain, whatif or sweep.
---

# Show a decision check as a Page

The module does not render documents. Write the Page with the bot's own Page tool, from the JSON the module returned. Use only values from the envelope; never compute a total, a difference or a threshold yourself, and never add a recommendation the module did not return.

Lay the Page out in this order:

1. **The question**, in the person's words, the model's name and version, and the scenario.
2. **What was proved.** One line with the module's `status`. For `feasible`, add that the search stopped at its limit and a better plan may exist, with the `bound`. For `unknown`, say there is no answer yet.
3. **What it rests on.** When `rests_on_assumptions` is not empty, list those constraints by label, above the result, under the heading "This result depends on unverified assumptions".
4. **The result.**
   - `solve`: the chosen values by variable description, the objective, and each entry of `soft_violated` as something the plan gives up, with its weight.
   - `explain`: each conflict set as "These cannot all hold", one line per member with its label, category and evidence confidence, marking assumptions. Then each correction set, smallest first, as "Giving up these would make it possible". When `complete` is `false`, say more may exist.
   - `whatif`: one column per scenario with status and objective, then only the rows in `differences`.
   - `sweep`: the parameter, its current value, one row per grid point, and each entry of `flips` as "changes between X and Y".
5. **Evidence.** For every parameter and constraint shown, its source and confidence from the model.
6. **How to reproduce.** The `now`, `seed` and `version` from `meta`, the solver name and version, and the `run_id` when the run was recorded.

Do not show a result whose `checked.violations` is not empty; report the fault instead. Do not place credentials or private bot files on the Page. A correction set is an option for the person, not a decision: do not write it as a recommendation.
