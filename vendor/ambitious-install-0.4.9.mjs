#!/usr/bin/env node

// <define:AMBITIOUS_MIGRATIONS>
var define_AMBITIOUS_MIGRATIONS_default = [];

// packages/kit/src/cli/install-main.ts
import { parseArgs } from "node:util";

// packages/kit/src/domain/json.ts
var isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

// packages/kit/src/domain/envelope.ts
var INTERNAL_ERROR_CODES = /* @__PURE__ */ new Set(["E_DB", "E_MIGRATION", "E_INTERNAL"]);
var envelope = {
  ok: ({ schemaVersion, module, command, meta }, data) => ({
    ok: true,
    schemaVersion,
    module,
    command,
    data,
    errors: [],
    meta
  }),
  err: ({ schemaVersion, module, command, meta }, errors, data = {}) => ({ ok: false, schemaVersion, module, command, data, errors, meta })
};
var exitCodeOf = (result2) => {
  if (result2.ok) return 0;
  return result2.errors.some(({ code }) => INTERNAL_ERROR_CODES.has(code)) ? 2 : 1;
};
var serialize = (result2) => `${JSON.stringify(result2)}
`;
var MODULE_NAME = /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/;
var VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z.-]+)?$/;
var isModuleName = (value) => MODULE_NAME.test(value);
var isSemver = (value) => VERSION.test(value);

// packages/kit/src/domain/failure.ts
var Failure = class extends Error {
  errors;
  data;
  constructor(errors, data = {}) {
    super(errors.map(({ code, message }) => `${code}: ${message}`).join(" "));
    this.name = "Failure";
    this.errors = errors;
    this.data = data;
  }
};
var failure = (code, message, hint, data = {}) => new Failure([{ code, message, hint }], data);

// packages/kit/src/install/install.ts
import { createHash, randomBytes } from "node:crypto";
import { closeSync, constants, fchmodSync, fstatSync, fsyncSync, lstatSync as lstatSync2, mkdirSync, openSync, readFileSync, readlinkSync as readlinkSync2, renameSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join as join2 } from "node:path";

// packages/kit/src/paths/refuse-agent-data.ts
import { lstatSync, readlinkSync } from "node:fs";
import { dirname, isAbsolute, join, parse, resolve, sep } from "node:path";
var AGENT_DATA_ROOT = "/home/box/agent-data";
var DEFAULT_AMBITIOUS_HOME = "/workspace/ambitious";
var MAX_LINKS = 40;
var isUnder = (path, root) => path === root || path.startsWith(`${root}${sep}`);
var refuse = (path) => {
  throw failure(
    "E_FORBIDDEN_PATH",
    `The path ${path} is under ${AGENT_DATA_ROOT}/, which modules never read or write.`,
    "Use a path under AMBITIOUS_HOME, or omit --db to use the default."
  );
};
var linkTarget = (path) => {
  try {
    return lstatSync(path).isSymbolicLink() ? readlinkSync(path) : null;
  } catch {
    return null;
  }
};
var withLinksResolved = (path, forbidden) => {
  const follow = (current, pending, links) => {
    if (forbidden(current)) return current;
    const [segment, ...rest] = pending;
    if (segment === void 0) return current;
    const next = join(current, segment);
    if (forbidden(next)) return next;
    const target = linkTarget(next);
    if (target === null) return follow(next, rest, links);
    if (links >= MAX_LINKS) return next;
    const absolute = isAbsolute(target) ? target : resolve(dirname(next), target);
    const { root: root2 } = parse(absolute);
    return follow(root2, [...absolute.slice(root2.length).split(sep).filter((part) => part !== ""), ...rest], links + 1);
  };
  const { root } = parse(path);
  return follow(root, path.slice(root.length).split(sep).filter((part) => part !== ""), 0);
};
var refuseAgentData = (path) => {
  const absolute = resolve(path);
  if (isUnder(absolute, AGENT_DATA_ROOT)) refuse(path);
  const resolvedRoot = withLinksResolved(dirname(AGENT_DATA_ROOT), () => false);
  const roots = [AGENT_DATA_ROOT, join(resolvedRoot, "agent-data")];
  const forbidden = (resolved) => roots.some((root) => isUnder(resolved, root));
  if (forbidden(withLinksResolved(absolute, forbidden))) refuse(path);
  return absolute;
};
var ambitiousHome = (environment) => {
  const configured = environment.AMBITIOUS_HOME;
  return refuseAgentData(configured === void 0 || configured === "" ? DEFAULT_AMBITIOUS_HOME : configured);
};

// packages/kit/src/install/install.ts
var SUMS_FILE = "SHA256SUMS";
var SUMS_LINE = /^([0-9a-f]{64}) [ *](\S+)$/;
var sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
var parseSums = (text) => new Map(
  text.split("\n").flatMap((line) => {
    const [, hash, name] = SUMS_LINE.exec(line) ?? [];
    return hash === void 0 || name === void 0 ? [] : [[name, hash]];
  })
);
var formatSums = (sums) => [...sums].sort(([a], [b]) => a < b ? -1 : 1).map(([name, hash]) => `${hash}  ${name}
`).join("");
var unsafeFile = (path) => {
  throw failure("E_INSTALL_PATH", `The install target ${path} is not a regular file.`, "Remove the symlink or non-regular target after checking it with the owner, then retry. No link was activated through it.");
};
var refuseNonRegularFile = (path) => {
  const present = lstatSync2(path, { throwIfNoEntry: false });
  if (present !== void 0 && !present.isFile()) unsafeFile(path);
};
var readIfPresent = (path) => {
  refuseNonRegularFile(path);
  if (lstatSync2(path, { throwIfNoEntry: false }) === void 0) return null;
  const descriptor = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
  try {
    if (!fstatSync(descriptor).isFile()) unsafeFile(path);
    return readFileSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
};
var currentLink = (path) => lstatSync2(path, { throwIfNoEntry: false })?.isSymbolicLink() === true ? readlinkSync2(path) : null;
var temporaryPath = (directory, name) => join2(directory, `.${name}.${randomBytes(16).toString("hex")}.partial`);
var placeByRename = (directory, name, write) => {
  const target = join2(directory, name);
  refuseNonRegularFile(target);
  const temporary = temporaryPath(directory, name);
  const descriptor = openSync(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | (constants.O_NOFOLLOW ?? 0), 384);
  try {
    write(descriptor);
    fsyncSync(descriptor);
    const written = fstatSync(descriptor);
    const staged = lstatSync2(temporary);
    if (!staged.isFile() || staged.dev !== written.dev || staged.ino !== written.ino) unsafeFile(temporary);
    refuseNonRegularFile(target);
    renameSync(temporary, target);
  } finally {
    closeSync(descriptor);
    rmSync(temporary, { force: true });
  }
};
var fetched = async (download, fileName) => {
  try {
    return await download(fileName);
  } catch (error) {
    throw failure(
      "E_INSTALL_DOWNLOAD",
      `${fileName} could not be downloaded: ${error instanceof Error ? error.message : String(error)}.`,
      "Check the release address and the network, then run the installer again. The existing install was left as it was."
    );
  }
};
var pointLink = (bin, linkName, asset) => {
  const path = join2(bin, asset);
  if (lstatSync2(path, { throwIfNoEntry: false })?.isFile() !== true) unsafeFile(path);
  const temporary = temporaryPath(bin, linkName);
  symlinkSync(asset, temporary);
  try {
    if (lstatSync2(path, { throwIfNoEntry: false })?.isFile() !== true) unsafeFile(path);
    renameSync(temporary, join2(bin, linkName));
  } finally {
    rmSync(temporary, { force: true });
  }
};
var install = async ({ module, version, kind, home, download, pinned }) => {
  if (!isModuleName(module)) throw failure("E_USAGE", `"${module}" is not a module name.`, "Use the lower-case name after ambitious-, for example tasks.");
  if (!isSemver(version)) {
    throw failure("E_USAGE", `"${version}" is not an exact version.`, 'Name one exact semantic version, for example 0.3.1. The installer never resolves "latest".');
  }
  const bin = join2(refuseAgentData(home), "bin");
  const asset = `ambitious-${module}-${version}.${kind}`;
  const linkName = `ambitious-${module}`;
  const path = join2(bin, asset);
  const link = join2(bin, linkName);
  const outcome = (action, hash) => ({ action, asset, path, link, sha256: hash });
  const switchLink = () => pointLink(bin, linkName, asset);
  const installedSums = parseSums(readIfPresent(join2(bin, SUMS_FILE))?.toString("utf8") ?? "");
  const recorded = installedSums.get(asset);
  const present = readIfPresent(path);
  if (present !== null && recorded !== void 0 && sha256(present) === recorded && (pinned === void 0 || pinned === recorded)) {
    if (currentLink(link) === asset) return outcome("unchanged", recorded);
    switchLink();
    return outcome("relinked", recorded);
  }
  const expected = parseSums(new TextDecoder().decode(await fetched(download, SUMS_FILE))).get(asset);
  if (expected === void 0) {
    throw failure(
      "E_INSTALL_CHECKSUM",
      `The release's ${SUMS_FILE} has no line for ${asset}.`,
      "Check the module name, version and release address. The existing install was left as it was."
    );
  }
  if (pinned !== void 0 && expected !== pinned) {
    throw failure(
      "E_INSTALL_CHECKSUM",
      `The release's ${SUMS_FILE} lists SHA-256 ${expected} for ${asset}, but the pinned checksum is ${pinned}.`,
      "The release and the pin disagree, so nothing was installed. Report it; do not edit the pin. The existing install was left as it was."
    );
  }
  const bytes = await fetched(download, asset);
  const actual = sha256(bytes);
  if (actual !== expected) {
    throw failure(
      "E_INSTALL_CHECKSUM",
      `The downloaded ${asset} has SHA-256 ${actual}, but ${SUMS_FILE} lists ${expected}.`,
      "Run the installer again. If it keeps failing, the release is damaged. The existing install was left as it was."
    );
  }
  mkdirSync(bin, { recursive: true });
  refuseNonRegularFile(path);
  refuseNonRegularFile(join2(bin, SUMS_FILE));
  placeByRename(bin, asset, (descriptor) => {
    writeFileSync(descriptor, bytes);
    fchmodSync(descriptor, 493);
  });
  placeByRename(bin, SUMS_FILE, (descriptor) => writeFileSync(descriptor, formatSums(new Map([...installedSums, [asset, expected]]))));
  switchLink();
  return outcome(present === null ? "installed" : "replaced", expected);
};

// packages/kit/src/install/runtime.ts
import { execFile } from "node:child_process";
import { createHash as createHash2, randomBytes as randomBytes2 } from "node:crypto";
import { existsSync, mkdirSync as mkdirSync2, readFileSync as readFileSync2, renameSync as renameSync2, rmSync as rmSync2, writeFileSync as writeFileSync2 } from "node:fs";
import { join as join3 } from "node:path";
var RUNTIME_MARKER = "ambitious-runtime.json";
var RUNTIME_LOCK = "requirements.txt";
var HASHED_PIN = /^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.!+_-]+(?:\s+--hash=sha256:[0-9a-f]{64})+$/;
var sha2562 = (bytes) => createHash2("sha256").update(bytes).digest("hex");
var runtimeLockAsset = (module, version) => `ambitious-${module}-${version}.runtime.txt`;
var runtimeLockProblems = (text) => {
  const pins = text.replace(/\\\n/g, " ").split("\n").map((line) => line.trim()).filter((line) => line !== "");
  const loose = pins.filter((line) => !HASHED_PIN.test(line));
  return [
    ...pins.length === 0 ? ["The runtime lock lists no package."] : [],
    ...loose.map((line) => `The runtime lock line "${line.slice(0, 80)}" is not one exact version with at least one --hash=sha256: value.`)
  ];
};
var markerMatches = (directory, lockSha256) => {
  try {
    const marker = JSON.parse(readFileSync2(join3(directory, RUNTIME_MARKER), "utf8"));
    return isRecord(marker) && marker.lockSha256 === lockSha256;
  } catch {
    return false;
  }
};
var fetched2 = async (download, fileName) => {
  try {
    return await download(fileName);
  } catch (error) {
    throw failure(
      "E_INSTALL_DOWNLOAD",
      `${fileName} could not be downloaded: ${error instanceof Error ? error.message : String(error)}.`,
      "Check the release address and the network, then run the installer again. No runtime was put in place."
    );
  }
};
var systemTool = (program, args) => new Promise((resolve2, reject) => {
  execFile(program, [...args], { maxBuffer: 64 * 1024 * 1024 }, (error, _stdout, stderr) => {
    if (error === null) resolve2();
    else reject(new Error(String(stderr).trim().split("\n").slice(-3).join(" ") || error.message));
  });
});
var installRuntime = async ({ module, version, home, download, runTool, python = "python3", pinned }) => {
  if (!isModuleName(module)) throw failure("E_USAGE", `"${module}" is not a module name.`, "Use the lower-case name after ambitious-, for example tasks.");
  if (!isSemver(version)) throw failure("E_USAGE", `"${version}" is not an exact version.`, "Name one exact semantic version, for example 0.3.1.");
  const root = refuseAgentData(home);
  const bin = join3(root, "bin");
  const runtimes = join3(root, module, "runtime");
  const lock = runtimeLockAsset(module, version);
  const outcome = (action, lockSha256) => ({ action, lock, lockSha256, path: join3(runtimes, lockSha256) });
  refuseNonRegularFile(join3(bin, SUMS_FILE));
  const installedSums = parseSums(existsSync(join3(bin, SUMS_FILE)) ? readFileSync2(join3(bin, SUMS_FILE), "utf8") : "");
  const recorded = installedSums.get(lock);
  if (recorded !== void 0 && (pinned === void 0 || pinned === recorded) && markerMatches(join3(runtimes, recorded), recorded)) return outcome("unchanged", recorded);
  const expected = parseSums(new TextDecoder().decode(await fetched2(download, SUMS_FILE))).get(lock);
  if (expected === void 0) {
    throw failure(
      "E_INSTALL_CHECKSUM",
      `The release's ${SUMS_FILE} has no line for ${lock}.`,
      "This release declares no pinned runtime, or the module name or version is wrong. Run the installer without --runtime, or check the release."
    );
  }
  if (pinned !== void 0 && expected !== pinned) {
    throw failure(
      "E_INSTALL_CHECKSUM",
      `The release's ${SUMS_FILE} lists SHA-256 ${expected} for ${lock}, but the pinned checksum is ${pinned}.`,
      "The release and the pin disagree, so no runtime was built. Report it; do not edit the pin. Any existing runtime was left as it was."
    );
  }
  const bytes = await fetched2(download, lock);
  const actual = sha2562(bytes);
  if (actual !== expected) {
    throw failure(
      "E_INSTALL_CHECKSUM",
      `The downloaded ${lock} has SHA-256 ${actual}, but ${SUMS_FILE} lists ${expected}.`,
      "Run the installer again. If it keeps failing, the release is damaged. No runtime was put in place."
    );
  }
  const text = new TextDecoder().decode(bytes);
  const loose = runtimeLockProblems(text);
  if (loose.length > 0) {
    throw failure("E_INSTALL_RUNTIME", loose.join(" "), "The release's runtime lock must pin every package to one version with its SHA-256. Report it; nothing was installed.");
  }
  const final = join3(runtimes, expected);
  const record = () => {
    mkdirSync2(bin, { recursive: true });
    const lines = [...new Map([...installedSums, [lock, expected]])].sort(([a], [b]) => a < b ? -1 : 1);
    placeByRename(bin, SUMS_FILE, (descriptor) => writeFileSync2(descriptor, lines.map(([name, hash]) => `${hash}  ${name}
`).join("")));
  };
  if (markerMatches(final, expected)) {
    record();
    return outcome("unchanged", expected);
  }
  mkdirSync2(runtimes, { recursive: true });
  const staging = join3(runtimes, `.${expected}.${randomBytes2(8).toString("hex")}.partial`);
  try {
    try {
      await runTool(python, ["-m", "venv", staging]);
      writeFileSync2(join3(staging, RUNTIME_LOCK), bytes);
      await runTool(join3(staging, "bin", "python"), [
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--no-deps",
        "--require-hashes",
        "--only-binary",
        ":all:",
        "--requirement",
        join3(staging, RUNTIME_LOCK)
      ]);
    } catch (error) {
      throw failure(
        "E_INSTALL_RUNTIME",
        `The pinned runtime for ${module} ${version} could not be built: ${error instanceof Error ? error.message : String(error)}.`,
        "Check that python3 can create a virtual environment (python3 -m venv) and that the package index can be reached, then run the installer again. No runtime was put in place."
      );
    }
    writeFileSync2(join3(staging, RUNTIME_MARKER), `${JSON.stringify({ module, version, lockSha256: expected })}
`);
    rmSync2(final, { recursive: true, force: true });
    renameSync2(staging, final);
  } finally {
    rmSync2(staging, { recursive: true, force: true });
  }
  record();
  return outcome("installed", expected);
};

// packages/kit/src/install/source.ts
import { readFile } from "node:fs/promises";
import { join as join4 } from "node:path";
var fromDirectory = (directory) => {
  const root = refuseAgentData(directory);
  return async (fileName) => readFile(join4(root, fileName));
};
var fromWeb = (base) => async (fileName) => {
  const response = await fetch(`${base.replace(/\/+$/, "")}/${fileName}`, { redirect: "follow" });
  if (!response.ok) throw new Error(`the server answered ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
};
var releaseSource = (from) => {
  if (from.startsWith("https://")) return fromWeb(from);
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(from)) {
    throw failure("E_USAGE", `The release address ${from} is not an https address.`, "Give an https:// address or the path of a directory that holds the release files.");
  }
  return fromDirectory(from);
};

// packages/kit/src/cli/embedded.ts
var embedded = () => {
  if (typeof define_AMBITIOUS_MIGRATIONS_default === "undefined") {
    throw new Error(
      "The module name, version and migrations are embedded when the binary is bundled. Build with bundleOptions() from @ambitious/kit/build/bundle-options and run the file in dist/."
    );
  }
  return { module: "install", version: "0.4.9", migrations: define_AMBITIOUS_MIGRATIONS_default };
};

// packages/kit/src/cli/install-main.ts
var USAGE = "ambitious-install <module> <version> --from <https address or directory of the release> [--kind mjs|pyz] [--runtime]";
var isKind = (value) => value === "mjs" || value === "pyz";
var request = (argv) => {
  const wrong = (message) => failure("E_USAGE", message, `Run it as: ${USAGE}`);
  const { positionals, values } = (() => {
    try {
      return parseArgs({
        args: [...argv],
        allowPositionals: true,
        options: { from: { type: "string" }, kind: { type: "string", default: "mjs" }, json: { type: "boolean" }, runtime: { type: "boolean", default: false } }
      });
    } catch (error) {
      throw wrong(error instanceof Error ? `${error.message}.` : "The arguments could not be read.");
    }
  })();
  const [module, version, ...extra] = positionals;
  if (module === void 0 || version === void 0 || extra.length > 0) throw wrong("Give exactly one module name and one exact version.");
  if (values.from === void 0) throw wrong("The release location --from is missing.");
  if (!isKind(values.kind)) throw wrong(`The asset kind "${values.kind}" is not mjs or pyz.`);
  return { module, version, kind: values.kind, from: values.from, runtime: values.runtime };
};
var run = async (argv, env) => {
  const identity = {
    schemaVersion: 1,
    module: "install",
    command: "install",
    meta: { now: (/* @__PURE__ */ new Date()).toISOString(), seed: 0, version: embedded().version }
  };
  try {
    const { from, runtime, ...wanted } = request(argv);
    const [home, download] = [ambitiousHome(env), releaseSource(from)];
    const installed = await install({ ...wanted, home, download });
    if (!runtime) return envelope.ok(identity, installed);
    return envelope.ok(identity, { ...installed, runtime: await installRuntime({ module: wanted.module, version: wanted.version, home, download, runTool: systemTool }) });
  } catch (error) {
    if (error instanceof Failure) return envelope.err(identity, error.errors, error.data);
    process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}
`);
    const internal = { code: "E_INTERNAL", message: "The installer hit an unexpected error.", hint: "Report it with the stderr log." };
    return envelope.err(identity, [internal]);
  }
};
var result = await run(process.argv.slice(2), process.env);
process.stdout.write(serialize(result));
process.exitCode = exitCodeOf(result);
