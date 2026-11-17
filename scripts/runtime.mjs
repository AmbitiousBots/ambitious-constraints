#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const USAGE = `Usage: node scripts/runtime.mjs [AMBITIOUS_HOME directory]

Builds the release files in dist/ and installs them, with the pinned solver
runtime, into a home directory (default: .build/home, where the tests look
for the runtime). It runs the vendored kit installer exactly as a bot would:

  node vendor/ambitious-install-<version>.mjs constraints <version> --kind pyz --runtime --from dist

The first run downloads the locked packages from the package index. A later
run with the same lock changes nothing.

Exit code 0: the binary and the runtime are in place. 1: the build or the
install failed. 2: the vendored installer does not match vendor/SHA256SUMS.
`;

const root = join(import.meta.dirname, "..");
const [argument, ...extra] = process.argv.slice(2);

const run = (command, args) => spawnSync(command, args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });

const vendoredInstaller = () => {
  const line = readFileSync(join(root, "vendor", "SHA256SUMS"), "utf8")
    .split("\n")
    .map((entry) => /^([0-9a-f]{64}) {2}(ambitious-install-[0-9A-Za-z.+-]+\.mjs)$/.exec(entry))
    .find((match) => match !== null);
  if (line === undefined) return null;
  const [, expected, name] = line;
  const path = join(root, "vendor", name);
  return existsSync(path) && createHash("sha256").update(readFileSync(path)).digest("hex") === expected ? path : null;
};

const main = () => {
  const installer = vendoredInstaller();
  if (installer === null) {
    process.stderr.write("The kit installer under vendor/ is missing or does not match vendor/SHA256SUMS.\n");
    return 2;
  }
  const built = run(process.execPath, [join(root, "scripts", "py.mjs"), join("scripts", "build.py")]);
  if (built.status !== 0) return 1;
  const version = /ambitious-constraints-([0-9A-Za-z.+-]+)\.pyz/.exec(built.stdout)?.[1];
  if (version === undefined) {
    process.stderr.write("The build did not name the release asset.\n");
    return 1;
  }
  const home = argument ?? join(root, ".build", "home");
  const installed = spawnSync(process.execPath, [installer, "constraints", version, "--kind", "pyz", "--runtime", "--from", join(root, "dist")], {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
    env: { ...process.env, AMBITIOUS_HOME: home },
  });
  const envelope = (() => {
    try {
      return JSON.parse(installed.stdout);
    } catch {
      return null;
    }
  })();
  if (envelope?.ok !== true) {
    process.stderr.write(`${installed.stdout}\n`);
    return 1;
  }
  process.stdout.write(`binary ${envelope.data.action}, runtime ${envelope.data.runtime.action}: ${envelope.data.runtime.path}\n`);
  return 0;
};

if (argument === "--help" || extra.length > 0 || argument?.startsWith("--")) {
  (argument === "--help" ? process.stdout : process.stderr).write(USAGE);
  process.exitCode = argument === "--help" ? 0 : 2;
} else {
  process.exitCode = main();
}
