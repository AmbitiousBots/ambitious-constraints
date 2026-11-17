# Skills

A skill is a Markdown file the bot follows when it drives this module. Each skill is one directory under `skills/` with a `SKILL.md`.

| Directory | What it tells the bot |
| --- | --- |
| `constraints-for-bots` | How to build a model with the person, propose and commit it, solve, explain, compare and sweep, and what must be said with every result. |
| `constraints-page` | How to lay a result out as a Grok Bot Page. The module never renders documents. |

The names carry no `ambitious-` prefix here. If a kit release copies a skill into the Ambitious Bot template, that process adds the prefix and a `Template version:` line; do not add either here. This module is opt-in and is not pinned in the template.

## Rules

- A skill tells the bot to run the installed binary at `$AMBITIOUS_HOME/bin/ambitious-constraints`.
- Pass JSON on stdin or with `--in`, never both. Keep input files outside `/home/box/agent-data`.
- The bot reads the JSON envelope and the exit code. It must not invent a successful result, and it must not compute a number the module already returns.
- The module does not render documents. The bot writes Grok Bot Pages.
- Do not put credentials, private bot files, or paths under `/home/box/agent-data` in module input.
- In a skill body, do not mention another skill by an unprefixed name; say "this module's Page skill".
