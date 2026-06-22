# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from seerapi_models import MintmarkORM
from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import select

if TYPE_CHECKING:
    from seerapi_models.common import SixAttributes

    from ironsbot.plugins.seer_data.db import SeerAPISession

RANK_LIST_SIZE = 20
MIN_COMBINATION_PARTS = 2
ANGLE_MARKERS = {
    "一角": 1,
    "1角": 1,
    "１角": 1,
    "二角": 2,
    "两角": 2,
    "2角": 2,
    "２角": 2,
    "三角": 3,
    "3角": 3,
    "３角": 3,
    "四角": 4,
    "4角": 4,
    "４角": 4,
    "五角": 5,
    "5角": 5,
    "５角": 5,
    "六角": 6,
    "6角": 6,
    "６角": 6,
}
MINTMARK_QUALITY_TABLE = "mintmark_quality"
MISSING_MINTMARK_QUALITY_MESSAGE = (
    "❌ 数据库缺少刻印角数表 mintmark_quality，请先更新 IronsBot 数据库。"
)
AVAILABLE_STATS_TEXT = "攻击 / 防御 / 特攻 / 特防 / 速度 / 体力 / 盾 / 双攻 / 总和"

_MINTMARK_QUALITY_KEYS = ("Quality", "quality")


@dataclass(frozen=True, slots=True)
class StatSpec:
    key: str
    title: str
    components: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CountermarkStatRankCommand:
    stat: StatSpec | None
    scope: str
    angle_count: int | None = None


@dataclass(frozen=True, slots=True)
class CountermarkStatRankItem:
    mintmark: MintmarkORM
    attrs: SixAttributes
    value: float
    total: float
    class_name: str
    angle_count: int | None


BASE_STAT_ALIASES: dict[str, StatSpec] = {
    "攻击": StatSpec("atk", "物攻", ("atk",)),
    "物攻": StatSpec("atk", "物攻", ("atk",)),
    "防御": StatSpec("def_", "防御", ("def_",)),
    "物防": StatSpec("def_", "防御", ("def_",)),
    "特攻": StatSpec("sp_atk", "特攻", ("sp_atk",)),
    "特防": StatSpec("sp_def", "特防", ("sp_def",)),
    "速度": StatSpec("spd", "速度", ("spd",)),
    "速": StatSpec("spd", "速度", ("spd",)),
    "体力": StatSpec("hp", "体力", ("hp",)),
    "体": StatSpec("hp", "体力", ("hp",)),
    "血量": StatSpec("hp", "体力", ("hp",)),
    "生命": StatSpec("hp", "体力", ("hp",)),
}

COMPOSITE_STAT_ALIASES: dict[str, StatSpec] = {
    "盾": StatSpec("shield", "盾", ("def_", "sp_def")),
    "双防": StatSpec("shield", "盾", ("def_", "sp_def")),
    "双防和": StatSpec("shield", "盾", ("def_", "sp_def")),
    "防御特防": StatSpec("shield", "盾", ("def_", "sp_def")),
    "防御加特防": StatSpec("shield", "盾", ("def_", "sp_def")),
    "双攻": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "双攻和": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "攻击特攻": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "攻击加特攻": StatSpec("dual_atk", "双攻", ("atk", "sp_atk")),
    "总和": StatSpec("total", "总和", ("total",)),
    "总值": StatSpec("total", "总和", ("total",)),
    "总数值": StatSpec("total", "总和", ("total",)),
    "综合": StatSpec("total", "总和", ("total",)),
}

STAT_ALIASES: dict[str, StatSpec] = {
    **BASE_STAT_ALIASES,
    **COMPOSITE_STAT_ALIASES,
}

COMBINABLE_STAT_ALIASES: tuple[tuple[str, StatSpec], ...] = tuple(
    sorted(
        {
            **BASE_STAT_ALIASES,
            "盾": COMPOSITE_STAT_ALIASES["盾"],
            "双防": COMPOSITE_STAT_ALIASES["盾"],
            "双攻": COMPOSITE_STAT_ALIASES["双攻"],
        }.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def _normalize_command_text(text: str) -> str:
    return "".join(text.split()).lower()


_NON_STAT_COUNTERMARK_RANK_COMMANDS = {
    _normalize_command_text(command)
    for command in (
        "刻印榜",
        "刻印图鉴榜",
        "样本刻印榜",
        "样本刻印图鉴榜",
        "机器人刻印榜",
        "机器人刻印图鉴榜",
    )
}


def parse_countermark_stat_rank_command(
    text: str,
) -> CountermarkStatRankCommand | None:
    normalized = _normalize_command_text(text)
    has_angle_marker = any(marker in normalized for marker in ANGLE_MARKERS)
    has_countermark_marker = "刻印" in normalized
    if not normalized.endswith("榜") or (
        not has_countermark_marker and not has_angle_marker
    ):
        return None
    if normalized in _NON_STAT_COUNTERMARK_RANK_COMMANDS:
        return None

    scope = "all"
    stat_text = normalized
    for marker in ("所有", "全部", "全体"):
        if marker in stat_text:
            scope = "all"
            stat_text = stat_text.replace(marker, "")

    stat_text, has_all_marker = _strip_single_all_marker(stat_text)
    if has_all_marker:
        scope = "all"

    angle_count = None
    for marker, marker_angle_count in ANGLE_MARKERS.items():
        if marker in stat_text:
            scope = "angle"
            angle_count = marker_angle_count
            stat_text = stat_text.replace(marker, "")

    for marker in ("排行榜", "排行", "数值", "属性", "刻印", "榜"):
        stat_text = stat_text.replace(marker, "")

    stat = parse_stat_spec(stat_text)
    return CountermarkStatRankCommand(
        stat=stat,
        scope=scope,
        angle_count=angle_count,
    )


def parse_stat_spec(text: str) -> StatSpec | None:
    if stat := STAT_ALIASES.get(text):
        return stat

    remaining = text
    parts: list[StatSpec] = []
    while remaining:
        for alias, stat in COMBINABLE_STAT_ALIASES:
            if remaining.startswith(alias):
                parts.append(stat)
                remaining = remaining.removeprefix(alias)
                break
        else:
            return None

    if len(parts) < MIN_COMBINATION_PARTS:
        return None

    components: list[str] = []
    titles: list[str] = []
    for part in parts:
        components.extend(part.components or (part.key,))
        titles.append(part.title)

    return StatSpec(
        key="combo:" + "+".join(components),
        title="".join(titles),
        components=tuple(components),
    )


def load_mintmark_quality_session(session: SeerAPISession) -> dict[int, int]:
    try:
        rows = session.exec(
            text(
                f"SELECT mintmark_id, quality FROM {MINTMARK_QUALITY_TABLE}"
            )
        ).all()
    except SQLAlchemyError:
        return {}

    quality_map: dict[int, int] = {}
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else None
        if mapping is not None:
            mintmark_id = _coerce_quality(mapping["mintmark_id"])
            quality = _coerce_quality(mapping["quality"])
        else:
            mintmark_id = _coerce_quality(row[0])
            quality = _coerce_quality(row[1])
        if mintmark_id is not None and quality is not None:
            quality_map[mintmark_id] = quality
    return quality_map


def load_mintmarks(session: SeerAPISession) -> list[MintmarkORM]:
    statement = select(MintmarkORM).options(
        selectinload(MintmarkORM.ability_part).selectinload(
            AbilityPartORM.max_attr_value
        ),
        selectinload(MintmarkORM.skill_part),
        selectinload(MintmarkORM.universal_part).selectinload(
            UniversalPartORM.base_attr_value
        ),
        selectinload(MintmarkORM.universal_part).selectinload(
            UniversalPartORM.max_attr_value
        ),
        selectinload(MintmarkORM.universal_part).selectinload(
            UniversalPartORM.extra_attr_value
        ),
        selectinload(MintmarkORM.universal_part).selectinload(
            UniversalPartORM.mintmark_class
        ),
    )
    return list(session.exec(statement).all())


def collect_countermark_rank_items(
    mintmarks: list[MintmarkORM],
    command: CountermarkStatRankCommand,
    quality_map: dict[int, int],
) -> list[CountermarkStatRankItem]:
    if command.stat is None:
        return []

    result: list[CountermarkStatRankItem] = []
    for mintmark in mintmarks:
        class_name = _mintmark_class_name(mintmark)
        angle_count = _mintmark_angle_count(mintmark, quality_map)
        if command.angle_count is not None and angle_count != command.angle_count:
            continue

        attrs = _mark_attributes(mintmark)
        if attrs is None:
            continue

        value = _get_stat_value(attrs, command.stat)
        if value <= 0:
            continue

        result.append(
            CountermarkStatRankItem(
                mintmark=mintmark,
                attrs=attrs,
                value=value,
                total=float(attrs.total),
                class_name=class_name,
                angle_count=angle_count,
            )
        )

    return sorted(
        result,
        key=lambda item: (
            item.value,
            item.total,
            -item.mintmark.id,
        ),
        reverse=True,
    )


def build_countermark_stat_rank_message(
    command: CountermarkStatRankCommand,
    items: list[CountermarkStatRankItem],
    *,
    now_text: str | None = None,
) -> str:
    if command.stat is None:
        return (
            "❌ 刻印数值榜需要指定属性。\n"
            f"可用属性：{AVAILABLE_STATS_TEXT}\n"
            "例：刻印攻击榜 / 六角双攻榜 / 刻印盾体榜 / 特攻盾刻印榜 / 刻印总和榜"
        )

    scope_text = _scope_text(command)
    if not items:
        return (
            f"❌ 没有找到{scope_text}的{command.stat.title}数据。\n"
            "默认已查询全部刻印；如果只想筛选角数，可以发送："
            f"六角刻印{command.stat.title}榜 或 2角刻印{command.stat.title}榜"
        )

    timestamp = _now_text() if now_text is None else now_text
    lines = [
        f"💮【{scope_text}{command.stat.title}榜】（截至{timestamp}）",
        f"范围：{scope_text} | 展示前 {min(RANK_LIST_SIZE, len(items))} 名",
    ]
    lines.extend(
        _format_item_line(index, item, command.stat)
        for index, item in enumerate(items[:RANK_LIST_SIZE], start=1)
    )
    return "\n".join(lines)


def _now_text() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _scope_text(command: CountermarkStatRankCommand) -> str:
    if command.angle_count is not None:
        return f"{command.angle_count}角刻印"
    return "所有刻印"


def _strip_single_all_marker(text: str) -> tuple[str, bool]:
    all_scope = False
    if text.startswith("全刻印"):
        text = text.removeprefix("全")
        all_scope = True
    if text.startswith("刻印全"):
        text = "刻印" + text.removeprefix("刻印全")
        all_scope = True
    return text, all_scope


def _mark_attributes(mintmark: MintmarkORM) -> SixAttributes | None:
    part = mintmark.ability_part or mintmark.skill_part or mintmark.universal_part
    if isinstance(part, AbilityPartORM):
        if part.max_attr_value is None:
            return None
        attr = part.max_attr_value.to_model()
    elif isinstance(part, UniversalPartORM):
        if part.max_attr_value is None:
            return None
        attr = part.max_attr_value.to_model()
        if part.extra_attr_value:
            attr = attr + part.extra_attr_value.to_model()
    elif isinstance(part, SkillPartORM):
        return None
    else:
        return None

    return attr.round()


def _mintmark_class_name(mintmark: MintmarkORM) -> str:
    part = mintmark.universal_part
    if not isinstance(part, UniversalPartORM) or part.mintmark_class is None:
        return ""

    return part.mintmark_class.name


def _coerce_quality(value: object) -> int | None:
    try:
        quality = int(value)
    except (TypeError, ValueError):
        return None

    return quality if quality > 0 else None


def _object_quality(obj: object | None) -> int | None:
    if obj is None:
        return None

    for key in _MINTMARK_QUALITY_KEYS:
        quality = _coerce_quality(getattr(obj, key, None))
        if quality is not None:
            return quality

    if hasattr(obj, "model_dump"):
        dumped = obj.model_dump()
        for key in _MINTMARK_QUALITY_KEYS:
            quality = _coerce_quality(dumped.get(key))
            if quality is not None:
                return quality

    return None


def _configured_mintmark_quality(
    mintmark: MintmarkORM,
    quality_map: dict[int, int],
) -> int | None:
    return quality_map.get(mintmark.id)


def _mintmark_angle_count(
    mintmark: MintmarkORM,
    quality_map: dict[int, int],
) -> int | None:
    for quality in (
        _object_quality(mintmark),
        _object_quality(mintmark.ability_part),
        _object_quality(mintmark.skill_part),
        _object_quality(mintmark.universal_part),
        _configured_mintmark_quality(mintmark, quality_map),
    ):
        if quality is not None:
            return quality

    return None


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0")


def _get_stat_value(attrs: SixAttributes, stat: StatSpec) -> float:
    if stat.key == "total":
        return float(attrs.total)
    if stat.components:
        total = 0.0
        for component in stat.components:
            if component == "total":
                total += float(attrs.total)
            else:
                total += float(getattr(attrs, component))
        return total

    return float(getattr(attrs, stat.key))


def _format_item_line(
    index: int,
    item: CountermarkStatRankItem,
    stat: StatSpec,
) -> str:
    class_text = f" | {item.class_name}" if item.class_name else ""
    angle_text = f" | {item.angle_count}角" if item.angle_count else ""
    return (
        f"{index}. {item.mintmark.name}（{item.mintmark.id}）"
        f" {stat.title}{_format_number(item.value)}"
        f" | 总和{_format_number(item.total)}"
        f"{class_text}"
        f"{angle_text}"
    )
