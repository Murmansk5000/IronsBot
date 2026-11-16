# SPDX-License-Identifier: MIT
"""Opt-in, bounded structural evidence; never used to classify mentions."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ironsbot.core.platform import reference_digest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ironsbot.config.models.settings import Settings

logger = logging.getLogger(__name__)
MAX_EVENTS = 20
MAX_SECONDS = 600
MAX_BYTES = 512 * 1024
MAX_NODES = 96
MAX_DEPTH = 4
MAX_FIELDS = 32
MAX_ITEMS = 8
MAX_ENUM = 255
MAX_ENUM_TEXT = 24
MAX_TEXT_INSPECT = 8192
_AT_MARKER = re.compile(r"<@([!&]?)([^<>\s]{1,128})>")
_EVENTS = frozenset({"GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"})
_KEY = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,39}\Z")
_SENSITIVE = ("token", "secret", "password", "authorization", "credential", "url")
_ENUM_KEYS = frozenset(
    {
        "type",
        "msg_type",
        "message_type",
        "at_type",
        "mention_type",
        "target_type",
        "scope",
    }
)
_ENUM_VALUES = frozenset(
    {
        "all",
        "everyone",
        "at_all",
        "at",
        "mention",
        "text",
        "image",
        "reply",
        "quote",
        "member",
        "user",
        "bot",
    }
)
_TARGET_KEYS = frozenset(
    {"id", "qq", "target", "user_id", "member_openid", "target_id"}
)


class MentionDiagnosticError(ValueError):
    """A controlled diagnostic operation was rejected without event details."""


def _type_value(value: object) -> bool:
    return isinstance(value, str) and (
        value in _ENUM_VALUES
        or (
            len(value) <= MAX_ENUM_TEXT
            and re.fullmatch(r"[A-Z][A-Z_]*", value) is not None
        )
        or (
            value.isascii()
            and value.isdecimal()
            and len(value) <= len(str(MAX_ENUM))
            and int(value) <= MAX_ENUM
        )
    )


def _text_markers(value: str) -> list[dict[str, str]]:
    result = []
    for match in _AT_MARKER.finditer(value[:MAX_TEXT_INSPECT]):
        target = match[2]
        result.append(
            {
                "modifier": match[1],
                "target_kind": target
                if target in {"all", "everyone"}
                else "numeric"
                if target.isdecimal()
                else "opaque",
            }
        )
        if len(result) == MAX_ITEMS:
            break
    return result


def _valid_markers(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) <= MAX_ITEMS
        and all(
            isinstance(item, dict)
            and set(item) == {"modifier", "target_kind"}
            and item["modifier"] in {"", "!", "&"}
            and item["target_kind"] in {"all", "everyone", "numeric", "opaque"}
            for item in value
        )
    )


def _scalar_shape(value: object, key: str) -> dict[str, object]:
    if isinstance(value, bool):
        return {"kind": "bool", "value": value}
    if isinstance(value, int):
        result: dict[str, object] = {"kind": "int"}
        if (key in _ENUM_KEYS and 0 <= value <= MAX_ENUM) or (
            ("all" in key or "everyone" in key) and value in (0, 1)
        ):
            result["value"] = value
        return result
    if isinstance(value, str):
        result = {"kind": "str", "length": len(value)}
        if (key in _ENUM_KEYS and _type_value(value)) or (
            key in _TARGET_KEYS and value in {"all", "everyone", "0"}
        ):
            result["value"] = value
        if key in {"content", "text"} and (markers := _text_markers(value)):
            result["mention_markup"] = markers
        return result
    return {"kind": "null" if value is None else "other"}


def _shape(value: object, key: str, depth: int, budget: list[int]) -> object:
    budget[0] -= 1
    if any(part in key.lower() for part in _SENSITIVE):
        return {"kind": "redacted"}
    if budget[0] < 0 or depth > MAX_DEPTH:
        return {"kind": "bounded"}
    if isinstance(value, Mapping):
        fields = {}
        for index, (name, item) in enumerate(value.items()):
            if index >= MAX_FIELDS or budget[0] <= 0:
                break
            if isinstance(name, str) and _KEY.fullmatch(name):
                fields[name] = _shape(item, name, depth + 1, budget)
        return {"kind": "object", "fields": fields}
    if isinstance(value, (tuple, list)):
        return {
            "kind": "array",
            "count": len(value),
            "items": [
                _shape(item, key, depth + 1, budget)
                for item in value[:MAX_ITEMS]
                if budget[0] > 0
            ],
        }
    return _scalar_shape(value, key)


def _valid_shape(node: object, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0 or not isinstance(node, dict):
        return False
    kind = node.get("kind")
    keys = set(node)
    if kind in {"redacted", "bounded", "null", "other"}:
        return keys == {"kind"}
    if kind == "object":
        fields = node.get("fields")
        return (
            keys == {"kind", "fields"}
            and isinstance(fields, dict)
            and len(fields) <= MAX_FIELDS
            and all(
                isinstance(key, str)
                and _KEY.fullmatch(key)
                and _valid_shape(value, budget)
                for key, value in fields.items()
            )
        )
    if kind == "array":
        items, count = node.get("items"), node.get("count")
        return (
            keys == {"kind", "items", "count"}
            and isinstance(items, list)
            and len(items) <= MAX_ITEMS
            and type(count) is int
            and count >= len(items)
            and all(_valid_shape(item, budget) for item in items)
        )
    return _valid_scalar(node)


def _valid_scalar(node: dict[str, Any]) -> bool:
    kind, keys = node.get("kind"), set(node)
    if kind == "str":
        return (
            {"kind", "length"} <= keys <= {"kind", "length", "value", "mention_markup"}
            and type(node.get("length")) is int
            and node["length"] >= 0
            and (
                "value" not in node
                or _type_value(node["value"])
                or node["value"] == "0"
            )
            and ("mention_markup" not in node or _valid_markers(node["mention_markup"]))
        )
    if kind == "int":
        return keys == {"kind"} or (
            keys == {"kind", "value"}
            and type(node["value"]) is int
            and 0 <= node["value"] <= MAX_ENUM
        )
    return (
        kind == "bool" and keys == {"kind", "value"} and isinstance(node["value"], bool)
    )


class QQMentionDiagnostics:
    def __init__(
        self,
        directory: Path,
        *,
        trusted_targets: frozenset[tuple[str, str]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.directory = directory
        self.control = directory / "control.json"
        self.trusted_targets = trusted_targets
        self.clock = clock
        self._warned = False
        self._observe_lock = asyncio.Lock()

    @contextmanager
    def _lock(self) -> Iterator[bool]:
        path = self.directory / "control.lock"
        if self.directory.is_symlink():
            raise MentionDiagnosticError("unsafe_directory")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            yield False
            return
        try:
            yield True
        finally:
            os.close(fd)
            path.unlink()

    def _read(self) -> dict[str, Any] | None:
        if not self.control.exists():
            return None
        if self.control.is_symlink() or self.control.stat().st_size > MAX_BYTES:
            raise MentionDiagnosticError("unsafe_control")
        state = json.loads(self.control.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or set(state) != {
            "schema_version",
            "session_id",
            "app_id",
            "group_ref",
            "created_at",
            "expires_at",
            "enabled",
            "records",
        }:
            raise MentionDiagnosticError("invalid_state")
        start, end = state["created_at"], state["expires_at"]
        if (
            state["schema_version"] != 1
            or not isinstance(state["enabled"], bool)
            or not isinstance(start, (int, float))
            or isinstance(start, bool)
            or not isinstance(end, (int, float))
            or isinstance(end, bool)
            or not math.isfinite(start)
            or not math.isfinite(end)
            or not 0 < end - start <= MAX_SECONDS
            or not isinstance(state["records"], list)
            or len(state["records"]) > MAX_EVENTS
            or not all(
                isinstance(state[key], str) and state[key]
                for key in ("session_id", "app_id", "group_ref")
            )
            or not all(
                isinstance(record, dict)
                and set(record) == {"captured_at", "event_type", "message_ref", "shape"}
                and record["event_type"] in _EVENTS
                and isinstance(record["captured_at"], (float, int))
                and not isinstance(record["captured_at"], bool)
                and start <= record["captured_at"] < end
                and (
                    record["message_ref"] is None
                    or (
                        isinstance(record["message_ref"], str)
                        and re.fullmatch(r"[0-9a-f]{12}", record["message_ref"])
                    )
                )
                and _valid_shape(record["shape"], [MAX_NODES])
                for record in state["records"]
            )
        ):
            raise MentionDiagnosticError("invalid_state")
        return state

    def _write(self, state: dict[str, Any]) -> None:
        raw = json.dumps(state, ensure_ascii=True, separators=(",", ":"))
        if len(raw.encode()) > MAX_BYTES:
            raise MentionDiagnosticError("state_too_large")
        temporary = self.directory / f".control-{uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            temporary.replace(self.control)
        finally:
            temporary.unlink(missing_ok=True)

    def enable(self, app_id: str, group_openid: str) -> dict[str, Any]:
        if (app_id, group_openid) not in self.trusted_targets:
            raise MentionDiagnosticError("untrusted_target")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._lock() as locked:
            if not locked:
                raise MentionDiagnosticError("busy")
            if self._read() is not None:
                raise MentionDiagnosticError("session_exists")
            now = self.clock()
            state = {
                "schema_version": 1,
                "session_id": uuid4().hex,
                "app_id": app_id,
                "group_ref": reference_digest(group_openid),
                "created_at": now,
                "expires_at": now + MAX_SECONDS,
                "enabled": True,
                "records": [],
            }
            self._write(state)
        return self.status()

    def status(self) -> dict[str, Any]:
        state = self._read()
        if state is None:
            return {"active": False, "count": 0}
        now = self.clock()
        return {
            **state,
            "count": len(state["records"]),
            "active": state["enabled"]
            and state["created_at"] <= now < state["expires_at"]
            and len(state["records"]) < MAX_EVENTS,
        }

    def disable(self, *, clear: bool = False) -> None:
        if not self.control.exists():
            return
        with self._lock() as locked:
            if not locked:
                raise MentionDiagnosticError("busy")
            if clear:
                self.control.unlink(missing_ok=True)
            elif (state := self._read()) is not None:
                state["enabled"] = False
                self._write(state)

    async def observe(
        self, app_id: str, event_type: str, raw: Mapping[str, object]
    ) -> None:
        group = raw.get("group_openid")
        if (
            event_type not in _EVENTS
            or not isinstance(group, str)
            or (app_id, group) not in self.trusted_targets
        ):
            return
        try:
            if self.control.exists():
                async with self._observe_lock:
                    await asyncio.to_thread(
                        self._record, app_id, event_type, group, raw
                    )
        except Exception:  # noqa: BLE001 - optional evidence must not stop message handling
            if not self._warned:
                logger.warning(
                    "QQ mention diagnostics unavailable; message processing continues"
                )
                self._warned = True

    def _record(
        self, app_id: str, event_type: str, group: str, raw: Mapping[str, object]
    ) -> None:
        with self._lock() as locked:
            if not locked:
                return
            state = self._read()
            now = self.clock()
            if (
                state is None
                or not state["enabled"]
                or not state["created_at"] <= now < state["expires_at"]
            ):
                return
            if (
                state["app_id"] != app_id
                or state["group_ref"] != reference_digest(group)
                or len(state["records"]) >= MAX_EVENTS
            ):
                return
            message_id = raw.get("id")
            message_ref = (
                reference_digest(str(message_id))
                if isinstance(message_id, (str, int))
                else None
            )
            if message_ref is not None and any(
                record.get("message_ref") == message_ref
                and record.get("event_type") == event_type
                for record in state["records"]
            ):
                return
            state["records"].append(
                {
                    "captured_at": now,
                    "event_type": event_type,
                    "message_ref": message_ref,
                    "shape": _shape(raw, "", 0, [MAX_NODES]),
                }
            )
            if len(state["records"]) >= MAX_EVENTS:
                state["enabled"] = False
            self._write(state)


def diagnostics_from_settings(settings: Settings) -> QQMentionDiagnostics:
    return QQMentionDiagnostics(
        settings.paths.runtime_state.parent / "mention_diagnostics",
        trusted_targets=frozenset(
            (account.app_id, group.official[alias])
            for alias, account in settings.bot.qq_official.enabled_accounts.items()
            for group in settings.identities.groups.values()
            if alias in group.official
        ),
    )


def main() -> None:
    import argparse

    from ironsbot.config.loader import load_settings

    parser = argparse.ArgumentParser(
        description="Bounded QQ mention structure diagnostics"
    )
    parser.add_argument("action", choices=("enable", "status", "disable", "clear"))
    parser.add_argument("--account", default="")
    parser.add_argument("--group", default="")
    args = parser.parse_args()
    settings = load_settings()
    diagnostics = diagnostics_from_settings(settings)
    try:
        if args.action == "enable":
            account = settings.bot.qq_official.enabled_accounts[args.account]
            group = settings.identities.groups[args.group].official[args.account]
            result = diagnostics.enable(account.app_id, group)
        elif args.action == "status":
            result = diagnostics.status()
        else:
            diagnostics.disable(clear=args.action == "clear")
            result = diagnostics.status()
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        sys.stdout.write(
            json.dumps({"ok": False, "error_type": type(error).__name__}) + "\n"
        )
        raise SystemExit(2) from None
    sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")


if __name__ == "__main__":
    main()
