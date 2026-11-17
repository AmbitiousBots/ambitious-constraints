from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ambitious_kit.domain.envelope import failure

from ambitious_constraints.domain.model import canonical


@dataclass(frozen=True)
class StoredModel:
    model_id: str
    name: str
    version: int
    latest: int
    digest: str
    doc: Mapping[str, object]
    actor: str
    at: str
    forked_from: Mapping[str, object] | None

    def reference(self) -> dict[str, object]:
        return {"id": self.model_id, "name": self.name, "version": self.version, "digest": self.digest}

    def to_json(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "version": self.version,
            "latest_version": self.latest,
            "digest": self.digest,
            "forked_from": self.forked_from,
            "actor": self.actor,
            "at": self.at,
            "model": self.doc,
        }


def _object(text: object) -> dict[str, object]:
    parsed: object = json.loads(text) if isinstance(text, str) else None
    if not isinstance(parsed, dict):
        raise failure(
            "E_DB",
            "Stored data does not match the database schema.",
            "Run selfcheck and restore a valid backup if needed.",
        )
    return parsed


def not_found(what: str) -> Exception:
    return failure("E_NOT_FOUND", f"{what} does not exist.", "Use model history or run list to find what is stored.")


def current_version(db: sqlite3.Connection, model_id: str) -> int:
    row = db.execute("SELECT version FROM models WHERE id = ?", (model_id,)).fetchone()
    return 0 if row is None else int(row[0])


def find_model(db: sqlite3.Connection, model_id: str, version: int | None = None) -> StoredModel | None:
    head = db.execute(
        "SELECT name, version, forked_from_id, forked_from_version FROM models WHERE id = ?", (model_id,)
    ).fetchone()
    if head is None:
        return None
    wanted = int(head[1]) if version is None else version
    row = db.execute(
        "SELECT digest, doc, actor, at FROM model_versions WHERE model_id = ? AND version = ?", (model_id, wanted)
    ).fetchone()
    if row is None:
        return None
    doc = _object(row[1])
    name = doc.get("name")
    forked = None if head[2] is None else {"model_id": str(head[2]), "version": int(head[3])}
    return StoredModel(
        model_id,
        name if isinstance(name, str) else str(head[0]),
        wanted,
        int(head[1]),
        str(row[0]),
        doc,
        str(row[2]),
        str(row[3]),
        forked,
    )


def get_model(db: sqlite3.Connection, model_id: str, version: int | None = None) -> StoredModel:
    found = find_model(db, model_id, version)
    if found is None:
        raise not_found(f"The model {model_id}" + ("" if version is None else f" version {version}"))
    return found


def with_receipt(
    db: sqlite3.Connection, idem_key: str, request: object, act: Callable[[], dict[str, object]]
) -> dict[str, object]:
    wanted = canonical(request)
    row = db.execute("SELECT request, response FROM request_receipts WHERE idem_key = ?", (idem_key,)).fetchone()
    if row is not None:
        if row[0] != wanted:
            raise failure(
                "E_IDEM_CONFLICT",
                f"The idem_key {idem_key} was already used for a different request.",
                "Retry with exactly the first request, or use a new idem_key for a new action.",
            )
        return {**_object(row[1]), "replayed": True}
    response = act()
    db.execute(
        "INSERT INTO request_receipts (idem_key, request, response) VALUES (?, ?, ?)",
        (idem_key, wanted, canonical(response)),
    )
    return {**response, "replayed": False}


def _event(
    db: sqlite3.Connection,
    kind: str,
    at: str,
    actor: str,
    model_id: str,
    version: int,
    digest: str,
    payload: object,
    idem_key: str,
) -> None:
    db.execute(
        "INSERT INTO model_events (at, actor, kind, model_id, version, digest, payload, idem_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (at, actor, kind, model_id, version, digest, canonical(payload), idem_key),
    )


def commit_model(
    db: sqlite3.Connection,
    *,
    model_id: str,
    base_version: int,
    digest: str,
    doc: Mapping[str, object],
    actor: str,
    at: str,
    idem_key: str,
) -> dict[str, object]:
    current = current_version(db, model_id)
    if current != base_version:
        raise failure(
            "E_STALE",
            f"The model {model_id} is at version {current}, "
            f"but this commit was prepared against version {base_version}.",
            "Run model propose against the current version, show the difference, "
            "and commit again with the new base_version.",
            {"model_id": model_id, "current_version": current, "base_version": base_version},
        )
    version = current + 1
    name = doc.get("name")
    title = name if isinstance(name, str) else model_id
    if current == 0:
        db.execute(
            "INSERT INTO models (id, name, version, digest, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (model_id, title, version, digest, at, at),
        )
    else:
        db.execute(
            "UPDATE models SET name = ?, version = ?, digest = ?, updated_at = ? WHERE id = ? AND version = ?",
            (title, version, digest, at, model_id, current),
        )
    db.execute(
        "INSERT INTO model_versions (model_id, version, digest, doc, actor, at) VALUES (?, ?, ?, ?, ?, ?)",
        (model_id, version, digest, canonical(doc), actor, at),
    )
    _event(db, "committed", at, actor, model_id, version, digest, {"base_version": base_version}, idem_key)
    return {"model_id": model_id, "version": version, "digest": digest}


def clone_model(
    db: sqlite3.Connection, *, source: StoredModel, new_id: str, actor: str, at: str, idem_key: str
) -> dict[str, object]:
    if current_version(db, new_id) != 0:
        raise failure(
            "E_EXISTS",
            f"The model {new_id} already exists.",
            "Choose a new_id that is not in use. A clone never overwrites a model.",
        )
    forked = {"model_id": source.model_id, "version": source.version}
    db.execute(
        "INSERT INTO models (id, name, version, digest, forked_from_id, forked_from_version, created_at, updated_at) "
        "VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
        (new_id, source.name, source.digest, source.model_id, source.version, at, at),
    )
    db.execute(
        "INSERT INTO model_versions (model_id, version, digest, doc, actor, at) VALUES (?, 1, ?, ?, ?, ?)",
        (new_id, source.digest, canonical(source.doc), actor, at),
    )
    _event(db, "cloned", at, actor, new_id, 1, source.digest, {"forked_from": forked}, idem_key)
    return {"model_id": new_id, "version": 1, "digest": source.digest, "forked_from": forked}


def model_history(db: sqlite3.Connection, model_id: str) -> list[dict[str, object]]:
    rows = db.execute(
        "SELECT seq, at, actor, kind, version, digest, payload FROM model_events WHERE model_id = ? ORDER BY seq",
        (model_id,),
    ).fetchall()
    if not rows:
        raise not_found(f"The model {model_id}")
    return [
        {
            "seq": int(row[0]),
            "at": str(row[1]),
            "actor": str(row[2]),
            "kind": str(row[3]),
            "version": int(row[4]),
            "digest": str(row[5]),
            **_object(row[6]),
        }
        for row in rows
    ]


def list_models(db: sqlite3.Connection) -> list[dict[str, object]]:
    rows = db.execute(
        "SELECT id, name, version, digest, forked_from_id, forked_from_version, updated_at FROM models ORDER BY id"
    ).fetchall()
    return [
        {
            "model_id": str(row[0]),
            "name": str(row[1]),
            "version": int(row[2]),
            "digest": str(row[3]),
            "forked_from": None if row[4] is None else {"model_id": str(row[4]), "version": int(row[5])},
            "updated_at": str(row[6]),
        }
        for row in rows
    ]


def record_run(
    db: sqlite3.Connection,
    *,
    run_id: str,
    at: str,
    actor: str,
    command: str,
    model_id: str | None,
    model_version: int | None,
    model_digest: str,
    seed: int,
    module_version: str,
    note: str | None,
    envelope: Mapping[str, object],
    idem_key: str,
) -> dict[str, object]:
    existing = db.execute("SELECT at FROM runs WHERE id = ?", (run_id,)).fetchone()
    if existing is None:
        db.execute(
            "INSERT INTO runs (id, at, actor, command, model_id, model_version, model_digest, seed, module_version, "
            "note, envelope, idem_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                at,
                actor,
                command,
                model_id,
                model_version,
                model_digest,
                seed,
                module_version,
                note,
                canonical(envelope),
                idem_key,
            ),
        )
    return {"run_id": run_id, "recorded": existing is None, "at": at if existing is None else str(existing[0])}


def _run_summary(row: tuple[object, ...]) -> dict[str, object]:
    return {
        "run_id": row[0],
        "at": row[1],
        "actor": row[2],
        "command": row[3],
        "model_id": row[4],
        "model_version": row[5],
        "model_digest": row[6],
        "seed": row[7],
        "module_version": row[8],
        "note": row[9],
    }


RUN_COLUMNS = "id, at, actor, command, model_id, model_version, model_digest, seed, module_version, note"


def get_run(db: sqlite3.Connection, run_id: str) -> dict[str, object]:
    row = db.execute(f"SELECT {RUN_COLUMNS}, envelope FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise not_found(f"The run {run_id}")
    return {**_run_summary(row[:10]), "envelope": _object(row[10])}


def list_runs(db: sqlite3.Connection, model_id: str | None) -> list[dict[str, object]]:
    rows = db.execute(
        f"SELECT {RUN_COLUMNS} FROM runs WHERE (? IS NULL OR model_id = ?) ORDER BY at, id", (model_id, model_id)
    ).fetchall()
    return [_run_summary(row) for row in rows]
