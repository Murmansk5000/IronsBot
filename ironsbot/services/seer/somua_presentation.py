# SPDX-License-Identifier: GPL-3.0-or-later
"""Readable Somua facts, independent of published storage and platform adapters."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.time import TZ_CN

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.services.seer.somua_models import SomuaDetail, SomuaParts

_GAME_CONTROL = re.compile(
    r"\[(?:/?color(?:=[^\]\r\n]*)?|sprite\s*name=[^\]\r\n]*|/?b|/?i|/?size(?:=[^\]\r\n]*)?)\]"
    r"|</?(?:sprite\b[^>\r\n]*|color(?:=[^>\r\n]*)?|size(?:=[^>\r\n]*)?|b|i)>",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SomuaEntryText:
    name: str
    description: str
    kind: int


@dataclass(frozen=True, slots=True)
class SomuaTextSnapshot:
    entries: Mapping[int, SomuaEntryText] = field(default_factory=dict)
    genes: Mapping[int, str] = field(default_factory=dict)
    parts: Mapping[int, str] = field(default_factory=dict)
    unavailable: tuple[str, ...] = ()


class SomuaTextResolver(Protocol):
    def resolve(self, detail: SomuaDetail) -> SomuaTextSnapshot: ...


def visible_somua_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    return _GAME_CONTROL.sub("", value).replace("|", "\n").strip()


def unknown_somua_value(value: int) -> str:
    return f"未识别（编号{value}）"


def format_somua_time(value: int) -> str:
    if value == 0:
        return "暂无记录"
    if value < 0:
        return "时间不可用"
    try:
        return datetime.fromtimestamp(value, TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return "时间不可用"


def _entry(value: int, snapshot: SomuaTextSnapshot, *, kind: int) -> str:
    entry = snapshot.entries.get(value)
    if (
        entry is None
        or entry.kind != kind
        or not (name := visible_somua_text(entry.name))
    ):
        return unknown_somua_value(value)
    description = visible_somua_text(entry.description)
    return f"{name}：{description}" if description else name


def _parts(parts: SomuaParts, snapshot: SomuaTextSnapshot) -> str:
    labels = ("身体", "表情", "手", "耳", "尾", "头", "上装", "背部", "环绕")
    result = []
    for label, value in zip(labels, asdict(parts).values(), strict=True):
        name = visible_somua_text(snapshot.parts.get(value, ""))
        result.append(
            f"{label}：{'无' if value == 0 else name or unknown_somua_value(value)}"
        )
    return "、".join(result)


def format_somua_detail(detail: SomuaDetail, snapshot: SomuaTextSnapshot) -> str:
    genes = "、".join(
        visible_somua_text(snapshot.genes.get(value, "")) or unknown_somua_value(value)
        for value in detail.genes
    )
    lines = [
        f"米米号：{detail.player_id}",
        f"名称：{detail.name or '未提供'}｜实例：{detail.sequence}",
        f"代数：{detail.generation}｜形态：{unknown_somua_value(detail.form_id)}｜"
        f"成长阶段：{unknown_somua_value(detail.stage)}",
        f"基因：{genes}",
        f"性格：{_entry(detail.personality, snapshot, kind=4)}",
        f"魂印：{_entry(detail.attack_mode, snapshot, kind=1)}",
        "【能力词条】",
        *(
            f"{index}. {_entry(value, snapshot, kind=3)}"
            for index, value in enumerate(detail.attributes, 1)
        ),
        f"外观：{_parts(detail.parts, snapshot)}",
        f"装备成就：{unknown_somua_value(detail.achievement_id)}｜"
        f"收藏标记：{unknown_somua_value(detail.is_collected)}",
        f"位置：{unknown_somua_value(detail.location)}｜"
        f"出战标记：{unknown_somua_value(detail.match_flag)}",
        f"创建时间：{format_somua_time(detail.created_at)}（北京时间）",
        f"上次互动：{format_somua_time(detail.last_touch_at)}（北京时间）",
    ]
    if snapshot.unavailable:
        lines.append("部分中文配置暂不可用：" + "、".join(snapshot.unavailable))
    return "\n".join(lines)
