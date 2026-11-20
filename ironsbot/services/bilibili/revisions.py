# SPDX-License-Identifier: MIT
"""Visible dynamic revisions, independent from platform IDs and counters."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

from .parser import dynamic_body_hydration_reason, dynamic_content, dynamic_image_urls

REVISION_META = "_ironsbot_edit"
REVISION_RETENTION = 24 * 60 * 60


def revision_meta(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get(REVISION_META)
    return value if isinstance(value, dict) else {}


def delivery_key(item: dict[str, Any]) -> str:
    return str(revision_meta(item).get("key") or item.get("id_str", ""))


def media_identity(url: str) -> str:
    return urlsplit(url).path.split("@", 1)[0]


def media_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return tuple(map(media_identity, dynamic_image_urls(before))) != tuple(
        map(media_identity, dynamic_image_urls(after))
    )


def visible_signature(item: dict[str, Any]) -> str:
    visible = (
        dynamic_content(item).replace("\r\n", "\n"),
        tuple(media_identity(url) for url in dynamic_image_urls(item)),
    )
    return hashlib.sha256(json.dumps(visible, ensure_ascii=False).encode()).hexdigest()


def complete_revision(item: dict[str, Any]) -> bool:
    modules = item.get("modules")
    if not isinstance(modules, dict):
        return False
    module = modules.get("module_dynamic")
    return (
        isinstance(module, dict)
        and _complete_media(item, module)
        and (
            isinstance(module.get("major"), dict)
            or item.get("type") in {"DYNAMIC_TYPE_WORD", "DYNAMIC_TYPE_FORWARD"}
        )
        and _complete_body(item, module)
        and bool(dynamic_content(item).strip() or dynamic_image_urls(item))
    )


def _complete_body(item: dict[str, Any], module: dict[str, Any]) -> bool:
    reason = dynamic_body_hydration_reason(item)
    if reason is None:
        return True
    desc = module.get("desc")
    major = module.get("major")
    opus = major.get("opus") if isinstance(major, dict) else None
    summary = opus.get("summary") if isinstance(opus, dict) else None
    return reason == "missing" and (
        isinstance(desc, str)
        or (isinstance(desc, dict) and isinstance(desc.get("text"), str))
        or (isinstance(summary, dict) and isinstance(summary.get("text"), str))
    )


def _complete_media(item: dict[str, Any], module: dict[str, Any]) -> bool:
    major = module.get("major")
    if not isinstance(major, dict):
        return item.get("type") in {"DYNAMIC_TYPE_WORD", "DYNAMIC_TYPE_FORWARD"}
    for name, field, url in (("draw", "items", "src"), ("opus", "pics", "url")):
        if name in major:
            value = major[name]
            pictures = value.get(field) if isinstance(value, dict) else None
            return isinstance(pictures, list) and all(
                isinstance(pic, dict) and isinstance(pic.get(url), str) and pic[url]
                for pic in pictures
            )
    return item.get("type") != "DYNAMIC_TYPE_DRAW"


def clean_revision(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != REVISION_META}
