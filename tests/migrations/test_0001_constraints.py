from __future__ import annotations

import sqlite3
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path

from ambitious_kit.db.sqlite import load_migrations, migrate, open_db, read_user_version

MIGRATIONS = load_migrations(files("ambitious_constraints") / "migrations")


class CreateConstraints(unittest.TestCase):
    def test_it_creates_the_tables_keeps_rows_and_sets_the_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = open_db(str(Path(directory) / "constraints.sqlite"), readonly=False)
            self.addCleanup(db.close)
            self.assertEqual(read_user_version(db), 0)
            self.assertEqual(migrate(db, MIGRATIONS[:1]), ["0001_constraints"])
            self.assertEqual(read_user_version(db), 1)
            db.execute("INSERT INTO models (id, name, version, digest, created_at, updated_at) VALUES ('m', 'M', 1, 'd', 't', 't')")
            db.execute("INSERT INTO model_versions (model_id, version, digest, doc, actor, at) VALUES ('m', 1, 'd', '{}', 'a', 't')")
            db.execute(
                "INSERT INTO model_events (at, actor, kind, model_id, version, digest, payload, idem_key) "
                "VALUES ('t', 'a', 'committed', 'm', 1, 'd', '{}', 'k')"
            )
            db.execute(
                "INSERT INTO runs (id, at, actor, command, model_digest, seed, module_version, envelope, idem_key) "
                "VALUES ('r', 't', 'a', 'solve', 'd', 1, '0.1.0', '{}', 'k')"
            )
            self.assertEqual(migrate(db, MIGRATIONS[:1]), [])
            self.assertEqual(db.execute("SELECT count(*) FROM model_versions").fetchone()[0], 1)
            for statement in (
                "INSERT INTO model_versions (model_id, version, digest, doc, actor, at) VALUES ('m', 2, 'd', 'not json', 'a', 't')",
                "INSERT INTO model_events (at, actor, kind, model_id, version, digest, payload, idem_key) VALUES ('t', 'a', 'renamed', 'm', 1, 'd', '{}', 'k2')",
                "INSERT INTO model_events (at, actor, kind, model_id, version, digest, payload, idem_key) VALUES ('t', 'a', 'cloned', 'm', 1, 'd', '{}', 'k')",
                "INSERT INTO models (id, name, version, digest, forked_from_id, created_at, updated_at) VALUES ('n', 'N', 1, 'd', 'm', 't', 't')",
                "UPDATE runs SET note = 'x'",
                "DELETE FROM runs",
            ):
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute(statement)


if __name__ == "__main__":
    unittest.main()
