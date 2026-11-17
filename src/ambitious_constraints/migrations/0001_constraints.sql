CREATE TABLE models (
  id TEXT PRIMARY KEY NOT NULL,
  name TEXT NOT NULL,
  version INTEGER NOT NULL CHECK (version >= 1),
  digest TEXT NOT NULL,
  forked_from_id TEXT,
  forked_from_version INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK ((forked_from_id IS NULL) = (forked_from_version IS NULL))
);

CREATE TABLE model_versions (
  model_id TEXT NOT NULL REFERENCES models(id),
  version INTEGER NOT NULL CHECK (version >= 1),
  digest TEXT NOT NULL,
  doc TEXT NOT NULL CHECK (json_valid(doc)),
  actor TEXT NOT NULL,
  at TEXT NOT NULL,
  PRIMARY KEY (model_id, version)
);

CREATE TABLE model_events (
  seq INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('committed', 'cloned')),
  model_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  digest TEXT NOT NULL,
  payload TEXT NOT NULL CHECK (json_valid(payload)),
  idem_key TEXT NOT NULL UNIQUE
);

CREATE TABLE runs (
  id TEXT PRIMARY KEY NOT NULL,
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  command TEXT NOT NULL CHECK (command IN ('solve', 'explain', 'whatif', 'sweep')),
  model_id TEXT,
  model_version INTEGER,
  model_digest TEXT NOT NULL,
  seed INTEGER NOT NULL,
  module_version TEXT NOT NULL,
  note TEXT,
  envelope TEXT NOT NULL CHECK (json_valid(envelope)),
  idem_key TEXT NOT NULL UNIQUE
);

CREATE TABLE request_receipts (
  idem_key TEXT PRIMARY KEY NOT NULL,
  request TEXT NOT NULL,
  response TEXT NOT NULL CHECK (json_valid(response))
);

CREATE INDEX model_events_by_model ON model_events(model_id, seq);
CREATE INDEX runs_by_model ON runs(model_id, at);

CREATE TRIGGER model_events_no_update BEFORE UPDATE ON model_events
BEGIN
  SELECT RAISE(ABORT, 'Model history is append-only');
END;

CREATE TRIGGER model_events_no_delete BEFORE DELETE ON model_events
BEGIN
  SELECT RAISE(ABORT, 'Model history is append-only');
END;

CREATE TRIGGER model_versions_no_update BEFORE UPDATE ON model_versions
BEGIN
  SELECT RAISE(ABORT, 'A stored model version never changes');
END;

CREATE TRIGGER model_versions_no_delete BEFORE DELETE ON model_versions
BEGIN
  SELECT RAISE(ABORT, 'A stored model version never changes');
END;

CREATE TRIGGER runs_no_update BEFORE UPDATE ON runs
BEGIN
  SELECT RAISE(ABORT, 'A recorded run never changes');
END;

CREATE TRIGGER runs_no_delete BEFORE DELETE ON runs
BEGIN
  SELECT RAISE(ABORT, 'A recorded run never changes');
END;
