# spec

TLA+ models of the behavior people rely on, checked by TLC, the TLA+ model checker.

- `X.tla` with `X.cfg` is a model. TLC must find no error in it.
- `broken/Y.tla` with `broken/Y.cfg` is a copy of a model with one protection removed. TLC must catch it breaking the invariant listed for it in `broken/EXPECTED.json`:

  ```json
  { "Y": { "invariant": "<name>", "because": "<plain sentence>" } }
  ```

A broken variant that passes, breaks a different invariant, or cannot be read fails the check: it means the model would not catch the mistake it was written to catch.

`ModelCommit` models how a stored model changes: writers propose against the version they saw, commit with that version and the proposed content, retry with the same request, start a new request, and clone a version. It checks four rules with two writers, two possible contents and up to three versions:

| Invariant | In plain words |
|---|---|
| `NoLostUpdate` | Every stored version was committed against the version just before it, so one writer never silently replaces what another stored. |
| `CommittedIsProposed` | The content stored under a receipt is the content that writer proposed. |
| `ReceiptNamesAStoredVersion` | A receipt never names a version that is not stored. |
| `CloneIsTheNamedVersion` | A clone holds exactly the content of the version it says it came from. |

`broken/CommitIgnoresBaseVersion` drops the comparison of `base_version` with the stored version, `broken/CommitWithoutDigest` drops the comparison of the model with its digest, and `broken/CloneCopiesLatest` copies the newest version instead of the named one.

## Run it

```text
mise trust && mise install
npm run tlc
```

[mise](https://mise.jdx.dev) installs the Java version pinned in `.mise.toml`. The same file pins `tla2tools.jar` (TLC) by exact address and SHA-256; `scripts/tla2tools.mjs` downloads it once into a cache directory and refuses a file whose hash differs. `npm run tlc` runs `tlc -workers 1 -config X.cfg X.tla` for every `.cfg` and ends with a table of what each model had to do and did.
