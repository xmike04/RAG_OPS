"""Strict, bounded validation for user-controlled document metadata."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class MetadataValidationError(ValueError):
    """Raised when metadata is not bounded JSON data."""


@dataclass(frozen=True, slots=True)
class MetadataLimits:
    max_depth: int = 8
    max_items: int = 256
    max_key_length: int = 128
    max_string_length: int = 16_384
    max_encoded_bytes: int = 65_536


def validate_metadata(
    metadata: Mapping[str, object] | None,
    *,
    limits: MetadataLimits = MetadataLimits(),
) -> dict[str, JsonValue]:
    """Return a detached, deterministically ordered JSON-compatible mapping."""

    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise MetadataValidationError("metadata must be an object")

    seen = 0

    def visit(value: object, path: str, depth: int) -> JsonValue:
        nonlocal seen
        if depth > limits.max_depth:
            raise MetadataValidationError(f"{path} exceeds maximum nesting depth")
        seen += 1
        if seen > limits.max_items:
            raise MetadataValidationError("metadata contains too many values")

        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise MetadataValidationError(f"{path} must be a finite number")
            return value
        if isinstance(value, str):
            if len(value) > limits.max_string_length:
                raise MetadataValidationError(f"{path} exceeds maximum string length")
            return value
        if isinstance(value, Mapping):
            output: dict[str, JsonValue] = {}
            keys = list(value)
            if any(not isinstance(key, str) for key in keys):
                raise MetadataValidationError(f"{path} contains a non-string key")
            for key in sorted(keys):
                if not isinstance(key, str):
                    raise MetadataValidationError(f"{path} contains a non-string key")
                if not key or len(key) > limits.max_key_length:
                    raise MetadataValidationError(f"{path} contains an invalid key")
                output[key] = visit(value[key], f"{path}.{key}", depth + 1)
            return output
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [visit(item, f"{path}[{index}]", depth + 1) for index, item in enumerate(value)]
        raise MetadataValidationError(
            f"{path} contains unsupported value type {type(value).__name__}"
        )

    result = visit(metadata, "metadata", 0)
    assert isinstance(result, dict)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > limits.max_encoded_bytes:
        raise MetadataValidationError("metadata exceeds maximum encoded size")
    return result
