# SPDX-License-Identifier: GPL-3.0-or-later
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State
from seerapi_models import MintmarkORM
from seerapi_models.common import SixAttributes
from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
from sqlmodel import select

from ironsbot.custom_plugins.message_actions import (
    finish_event_reply,
    normalize_command_text,
)
from ironsbot.plugins.seer_data.db import SeerAPISession
from ironsbot.utils.rule import no_reply

from ..group import matcher_group

RANK_LIST_SIZE = 20
FIVE_ANGLE_ATTR_COUNT = 5
FIVE_ANGLE_MARKERS = ("五角", "5角", "５角")
COUNTERMARK_STAT_RANK_KEY = "_countermark_stat_rank"
MINTMARK_QUALITY_KEYS = ("Quality", "quality")
MINTMARK_QUALITY_TABLE = "mintmark_quality"


@dataclass(frozen=True, slots=True)
class StatSpec:
    key: str
    title: str


@dataclass(frozen=True, slots=True)
class CountermarkStatRankCommand:
    stat: StatSpec | None
    scope: str


@dataclass(frozen=True, slots=True)
class CountermarkStatRankItem:
    mintmark: MintmarkORM
    attrs: SixAttributes
    value: float
    total: float
    class_name: str
    angle_count: int | None


STAT_ALIASES: dict[str, StatSpec] = {
    "攻击": StatSpec("atk", "攻击"),
    "物攻": StatSpec("atk", "攻击"),
    "防御": StatSpec("def_", "防御"),
    "物防": StatSpec("def_", "防御"),
    "特攻": StatSpec("sp_atk", "特攻"),
    "特防": StatSpec("sp_def", "特防"),
    "速度": StatSpec("spd", "速度"),
    "速": StatSpec("spd", "速度"),
    "体力": StatSpec("hp", "体力"),
    "血量": StatSpec("hp", "体力"),
    "生命": StatSpec("hp", "体力"),
    "总和": StatSpec("total", "总和"),
    "总值": StatSpec("total", "总和"),
    "总数值": StatSpec("total", "总和"),
    "综合": StatSpec("total", "总和"),
}

AVAILABLE_STATS_TEXT = "攻击 / 防御 / 特攻 / 特防 / 速度 / 体力 / 总和"


NON_STAT_COUNTERMARK_RANK_COMMANDS = {
    normalize_command_text(command)
    for command in (
        "刻印榜",
        "刻印图鉴榜",
        "样本刻印榜",
        "样本刻印图鉴榜",
        "机器人刻印榜",
        "机器人刻印图鉴榜",
    )
}


def _now_text() -> str:
    now = datetime.now(timezone(timedelta(hours=8)))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def _strip_single_all_marker(text: str) -> tuple[str, bool]:
    all_scope = False
    if text.startswith("全刻印"):
        text = text.removeprefix("全")
        all_scope = True
    if text.startswith("刻印全"):
        text = "刻印" + text.removeprefix("刻印全")
        all_scope = True
    return text, all_scope


def _parse_countermark_stat_rank_command(
    text: str,
) -> CountermarkStatRankCommand | None:
    normalized = normalize_command_text(text)
    if not normalized.endswith("榜") or "刻印" not in normalized:
        return None
    if normalized in NON_STAT_COUNTERMARK_RANK_COMMANDS:
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

    for marker in FIVE_ANGLE_MARKERS:
        if marker in stat_text:
            scope = "five"
            stat_text = stat_text.replace(marker, "")

    for marker in ("排行榜", "排行", "数值", "属性", "刻印", "榜"):
        stat_text = stat_text.replace(marker, "")

    stat = STAT_ALIASES.get(stat_text)
    return CountermarkStatRankCommand(stat=stat, scope=scope)


async def _is_countermark_stat_rank_command(event: Event, state: T_State) -> bool:
    command = _parse_countermark_stat_rank_command(event.get_plaintext())
    if command is None:
        return False

    state[COUNTERMARK_STAT_RANK_KEY] = command
    return True


countermark_stat_rank_matcher = matcher_group.on_message(
    rule=Rule(_is_countermark_stat_rank_command) & no_reply(),
)


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

    for key in MINTMARK_QUALITY_KEYS:
        quality = _coerce_quality(getattr(obj, key, None))
        if quality is not None:
            return quality

    if hasattr(obj, "model_dump"):
        dumped = obj.model_dump()
        for key in MINTMARK_QUALITY_KEYS:
            quality = _coerce_quality(dumped.get(key))
            if quality is not None:
                return quality

    return None


def _load_mintmark_quality_session(session: SeerAPISession) -> dict[int, int]:
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

    return float(getattr(attrs, stat.key))


def _collect_rank_items(
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
        if command.scope == "five" and angle_count != FIVE_ANGLE_ATTR_COUNT:
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


def _load_mintmarks(session: SeerAPISession) -> list[MintmarkORM]:
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


def _build_stat_rank_message(
    command: CountermarkStatRankCommand,
    items: list[CountermarkStatRankItem],
) -> str:
    if command.stat is None:
        return (
            "❌ 刻印数值榜需要指定属性。\n"
            f"可用属性：{AVAILABLE_STATS_TEXT}\n"
            "例：刻印攻击榜 / 五角刻印速度榜 / 5角刻印速度榜 / 刻印总和榜"
        )

    scope_text = "五角刻印" if command.scope == "five" else "所有刻印"
    if not items:
        return (
            f"❌ 没有找到{scope_text}的{command.stat.title}数据。\n"
            "默认已查询全部刻印；如果只想看五角，可以发送："
            f"五角刻印{command.stat.title}榜 或 5角刻印{command.stat.title}榜"
        )

    lines = [
        f"💮【{scope_text}{command.stat.title}榜】（截至{_now_text()}）",
        f"范围：{scope_text} | 展示前 {min(RANK_LIST_SIZE, len(items))} 名",
    ]
    lines.extend(
        _format_item_line(index, item, command.stat)
        for index, item in enumerate(items[:RANK_LIST_SIZE], start=1)
    )
    return "\n".join(lines)


@countermark_stat_rank_matcher.handle()
async def handle_countermark_stat_rank(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    session: SeerAPISession,
) -> None:
    command: CountermarkStatRankCommand = state[COUNTERMARK_STAT_RANK_KEY]
    quality_map = _load_mintmark_quality_session(session)
    if command.scope == "five" and not quality_map:
        await finish_event_reply(
            matcher,
            event,
            "❌ 数据库缺少刻印角数表 mintmark_quality，请先更新 IronsBot 数据库。",
        )
        return

    mintmarks = _load_mintmarks(session)
    items = _collect_rank_items(mintmarks, command, quality_map)
    await finish_event_reply(
        matcher,
        event,
        _build_stat_rank_message(command, items),
    )
