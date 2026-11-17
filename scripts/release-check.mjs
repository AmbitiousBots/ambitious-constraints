#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { join } from "node:path";

const USAGE = `Usage: node scripts/release-check.mjs

Runs every check a release must pass, in order, and stops at the first one
that fails: typecheck, lint, test, contract, tlc, verify. Needs python3 3.13
with the tools in scripts/dev-requirements.txt (or PY set to one that has
them), Node 24, and the Java pinned in .mise.toml for tlc.

Exit code 0: every step passed. Otherwise the failing step's exit code.
`;

const root = join(import.meta.dirname, "..");
const steps = ["typecheck", "lint", "test", "contract", "tlc", "verify"];

if (process.argv.length > 2) {
  (process.argv[2] === "--help" ? process.stdout : process.stderr).write(USAGE);
  process.exitCode = process.argv[2] === "--help" ? 0 : 2;
} else {
  for (const step of steps) {
    process.stdout.write(`\n=== npm run ${step}\n`);
    const result = spawnSync("npm", ["run", "--silent", step], { cwd: root, stdio: "inherit" });
    if (result.status !== 0) process.exit(result.status ?? 2);
  }
  process.stdout.write(`\nrelease check: ok. ${steps.length} of ${steps.length} steps passed.\n`);
}
