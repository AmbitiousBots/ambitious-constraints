from __future__ import annotations

from collections.abc import Mapping, Sequence

from ambitious_kit.domain.envelope import JsonObject, JsonValue


def json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [json_value(item) for item in value]
    raise TypeError(f"{type(value).__name__} is not a JSON value")


def json_object(value: Mapping[str, object]) -> JsonObject:
    return {key: json_value(item) for key, item in value.items()}
