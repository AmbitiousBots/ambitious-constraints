from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from ambitious_kit.domain.envelope import Failure, failure
from ambitious_kit.domain.json_schema import describe_schema_problems, schema_problems

from ambitious_constraints.domain.model import MODEL_SCHEMA

MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_DETERMINISTIC_TIME = 10
MAX_DETERMINISTIC_TIME = 600
DEFAULT_MAX_SETS = 20
MAX_SETS = 100
DEFAULT_MAX_DEPTH = 6
MAX_GRID = 200
MAX_SCENARIOS = 50
MAX_TEXT = 200
RUN_COMMANDS = ("solve", "explain", "whatif", "sweep")


def invalid(
    message: str, hint: str = "Read the command's input in the README and send one JSON object that matches it."
) -> Failure:
    return failure("E_INPUT_SCHEMA", message, hint)


def record(raw: object, allowed: tuple[str, ...]) -> Mapping[str, object]:
    if not isinstance(raw, dict):
        raise invalid("The input must be a JSON object.")
    extra = sorted(set(raw) - set(allowed))
    if extra:
        raise invalid(
            f'The input has the unexpected field "{extra[0]}".', f"Use only these fields: {', '.join(allowed)}."
        )
    return raw


def text(fields: Mapping[str, object], name: str) -> str:
    value = fields.get(name)
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_TEXT or value.strip() != value:
        raise invalid(f'The field "{name}" must be a string of 1 to {MAX_TEXT} characters with no surrounding spaces.')
    return value


def optional_text(fields: Mapping[str, object], name: str) -> str | None:
    return None if fields.get(name) is None else text(fields, name)


def model_id(fields: Mapping[str, object], name: str = "model_id") -> str:
    value = fields.get(name)
    if not isinstance(value, str) or MODEL_ID.fullmatch(value) is None:
        raise invalid(
            f'The field "{name}" must be a model id: '
            "lower-case letters, digits, dots, dashes or underscores, at most 64.",
            'Send a model id such as "pricing-2026".',
        )
    return value


def whole(fields: Mapping[str, object], name: str, minimum: int, maximum: int, default: int | None = None) -> int:
    value = fields.get(name)
    if value is None and default is not None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise invalid(f'The field "{name}" must be a whole number from {minimum} to {maximum}.')
    return value


def optional_whole(fields: Mapping[str, object], name: str, minimum: int, maximum: int) -> int | None:
    return None if fields.get(name) is None else whole(fields, name, minimum, maximum)


def sha256(fields: Mapping[str, object], name: str) -> str:
    value = fields.get(name)
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise invalid(
            f'The field "{name}" must be 64 lower-case hexadecimal characters: the digest that model propose returned.'
        )
    return value


def model_document(fields: Mapping[str, object], schema: object) -> Mapping[str, object]:
    model = fields.get("model")
    if not isinstance(model, dict):
        raise invalid(f'The field "model" must be a {MODEL_SCHEMA} document.')
    if model.get("schema") != MODEL_SCHEMA:
        raise invalid(
            f'The model\'s "schema" field is {model.get("schema")!r}; this module reads {MODEL_SCHEMA}.',
            f'Send a model whose "schema" field is "{MODEL_SCHEMA}".',
        )
    problems = schema_problems(schema, model)
    if problems:
        raise invalid(
            f"The model does not match {MODEL_SCHEMA}: {describe_schema_problems(problems[:5])}.",
            "Fix the named fields. model validate lists every problem.",
        )
    return model


@dataclass(frozen=True)
class Source:
    model: Mapping[str, object] | None
    model_id: str | None
    version: int | None


def source(fields: Mapping[str, object], schema: object) -> Source:
    inline, stored = fields.get("model") is not None, fields.get("model_id") is not None
    if inline == stored:
        raise invalid('Give exactly one of "model" (a model document) or "model_id" (a stored model).')
    if inline:
        if fields.get("version") is not None:
            raise invalid('"version" selects a stored model version, so it needs "model_id".')
        return Source(model_document(fields, schema), None, None)
    return Source(None, model_id(fields), optional_whole(fields, "version", 1, 2**31))


def deterministic_time(fields: Mapping[str, object]) -> int:
    limits = fields.get("limits")
    if limits is None:
        return DEFAULT_DETERMINISTIC_TIME
    return whole(
        record(limits, ("deterministic_time",)),
        "deterministic_time",
        1,
        MAX_DETERMINISTIC_TIME,
        DEFAULT_DETERMINISTIC_TIME,
    )
