#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { delimiter, join } from "node:path";

const USAGE = `Usage: node scripts/py.mjs <python arguments...>

Runs python3 from the repository root with the module's source, the vendored
kit and the example generators on the import path. Set PY to use another
Python 3.13 interpreter, for example one that has the lint tools installed.

Exit code: the command's own, or 2 when Python could not be started.
`;

const root = join(import.meta.dirname, "..");
const args = process.argv.slice(2);

if (args.length === 0 || args[0] === "--help") {
  (args.length === 0 ? process.stderr : process.stdout).write(USAGE);
  process.exitCode = args.length === 0 ? 2 : 0;
} else {
  const paths = ["src", "vendor", join("examples", "pricing")].map((path) => join(root, path));
  const result = spawnSync(process.env.PY ?? "python3", args, {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, PYTHONPATH: [...paths, process.env.PYTHONPATH ?? ""].filter((path) => path !== "").join(delimiter) },
  });
  if (result.error !== undefined) process.stderr.write(`Could not start Python: ${result.error.message}\n`);
  process.exitCode = result.error === undefined ? (result.status ?? 2) : 2;
}
