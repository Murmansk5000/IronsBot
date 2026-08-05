# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic final-cache keys for immutable render documents."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from . import RenderDocument


class RenderDocumentCacheKeyError(ValueError):
    """A render document contains a value unsuitable for deterministic caching."""


def render_document_cache_key(document: RenderDocument) -> str:
    """Hash every value that can change pixels in an immutable document.

    Integrations call this after their repository snapshot and assets have been
    prepared. Asset data URIs are therefore part of the key, so replacing an
    upstream image cannot reuse a final image rendered with the old bytes.
    """

    payload = _normalize(document)
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _normalize(value: object) -> Any:  # noqa: PLR0911
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RenderDocumentCacheKeyError
        return value
    if isinstance(value, bytes):
        return {"bytes": base64.b64encode(value).decode("ascii")}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "dataclass": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": tuple(
                (field.name, _normalize(getattr(value, field.name)))
                for field in fields(value)
            ),
        }
    if isinstance(value, Mapping):
        return {
            "mapping": tuple(
                (_normalize(key), _normalize(item))
                for key, item in value.items()
            )
        }
    if isinstance(value, tuple):
        return {"tuple": tuple(_normalize(item) for item in value)}
    if isinstance(value, list):
        return {"list": tuple(_normalize(item) for item in value)}
    if isinstance(value, (set, frozenset)):
        return {
            "set": tuple(
                sorted(
                    (_normalize(item) for item in value),
                    key=_mapping_key_sort_value,
                )
            )
        }
    raise RenderDocumentCacheKeyError


def _mapping_key_sort_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
