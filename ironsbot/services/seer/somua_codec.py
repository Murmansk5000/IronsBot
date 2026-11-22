# SPDX-License-Identifier: MIT
"""Strict client-verified Somua detail and persistent slot serialization."""

from __future__ import annotations

import json
import struct
from dataclasses import asdict
from typing import Any

from ironsbot.services.seer.somua_models import (
    SomuaCommonSlot,
    SomuaDetail,
    SomuaParent,
    SomuaParts,
)

_HEADER = struct.Struct("!I32s6I6I3I4I9I")
_PARENT = struct.Struct("!32sI9I16sI")
_TAIL = struct.Struct("!IBI")
_COMMON_SLOTS = 3
_UINT32_MAX = 0xFFFFFFFF


def _text(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def _parent(data: bytes, offset: int) -> SomuaParent:
    values = _PARENT.unpack_from(data, offset)
    return SomuaParent(
        _text(values[0]),
        values[1],
        SomuaParts(*values[2:11]),
        _text(values[11]),
        values[12],
    )


def parse_somua_detail(data: bytes, *, player_id: int, sequence: int) -> SomuaDetail:
    if len(data) != _HEADER.size + _PARENT.size * 2 + _TAIL.size:
        raise ValueError("苏摩详情数据长度异常")
    head = _HEADER.unpack_from(data)
    father = _parent(data, _HEADER.size)
    mother = _parent(data, _HEADER.size + _PARENT.size)
    achievement, collected, owner = _TAIL.unpack_from(data, len(data) - _TAIL.size)
    if head[0] != sequence or owner != player_id or sequence <= 0:
        raise ValueError("苏摩详情玩家或实例不一致")
    return SomuaDetail(
        sequence=head[0],
        name=_text(head[1]),
        generation=head[2],
        form_id=head[3],
        stage=head[4],
        created_at=head[5],
        last_touch_at=head[6],
        location=head[7],
        genes=tuple(head[8:14]),
        match_flag=head[14],
        attack_mode=head[15],
        personality=head[16],
        attributes=tuple(head[17:21]),
        parts=SomuaParts(*head[21:30]),
        father=father,
        mother=mother,
        achievement_id=achievement,
        is_collected=collected,
        player_id=owner,
    )


def encode_common_slots(slots: tuple[SomuaCommonSlot, ...]) -> str:
    return json.dumps([asdict(slot) for slot in slots], separators=(",", ":"))


def decode_common_slots(payload: str | None) -> tuple[SomuaCommonSlot, ...] | None:
    if payload is None:
        return None
    try:
        rows = json.loads(payload)
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(rows, list) or len(rows) != _COMMON_SLOTS:
        return None
    result = []
    for row in rows:
        slot = _decode_slot(row)
        if slot is None:
            return None
        result.append(slot)
    present = [slot.sequence for slot in result if slot.sequence]
    return tuple(result) if len(present) == len(set(present)) else None


def _decode_slot(row: Any) -> SomuaCommonSlot | None:
    if not isinstance(row, dict) or set(row) != {"sequence", "parts"}:
        return None
    parts = row["parts"]
    if not isinstance(parts, dict) or set(parts) != set(
        SomuaParts.__dataclass_fields__
    ):
        return None
    if any(
        type(value) is not int or not 0 <= value <= _UINT32_MAX
        for value in (row["sequence"], *parts.values())
    ):
        return None
    return SomuaCommonSlot(row["sequence"], SomuaParts(**parts))
