# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
import sqlite3
import struct
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State
from seerapi_models import MintmarkORM
from seerapi_models.common import SixAttributes
from seerapi_models.mintmark import AbilityPartORM, SkillPartORM, UniversalPartORM
from sqlalchemy.orm import selectinload
from sqlmodel import select

from ironsbot.custom_plugins.message_actions import finish_event_reply
from ironsbot.plugins.seer_data.db import SeerAPISession
from ironsbot.utils.rule import no_reply

from ..config import plugin_config
from ..group import matcher_group
from ._skin_price import (
    PACKAGE_NAME,
    _BytesReader,
    _extract_text_assets,
    _find_config_bundle,
)

RANK_LIST_SIZE = 20
FIVE_ANGLE_ATTR_COUNT = 5
FIVE_ANGLE_MARKERS = ("五角", "5角", "５角")
COUNTERMARK_STAT_RANK_KEY = "_countermark_stat_rank"
DEFAULT_MINTMARK_QUALITY_PATHS = (
    Path("data/custom_get_seer_info/mintmark.json"),
    Path("data/mintmark.json"),
    Path("../seer-unity-config-parser/json/mintmark.json"),
    Path("seer-unity-config-parser/json/mintmark.json"),
)
MINTMARK_ID_KEYS = ("ID", "id")
MINTMARK_QUALITY_KEYS = ("Quality", "quality")
MINTMARK_BYTES_NAME = "mintmark.bytes"
MINTMARK_QUALITY_TABLE = "mintmark_quality"

_MINTMARK_QUALITY_MAP: dict[int, int] | None = None
_MINTMARK_QUALITY_LOCK = asyncio.Lock()


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


def _normalize_command_text(text: str) -> str:
    return "".join(text.split()).lower()


NON_STAT_COUNTERMARK_RANK_COMMANDS = {
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
    normalized = _normalize_command_text(text)
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


def _configured_mintmark_quality_paths() -> list[Path]:
    configured = plugin_config.seer_query_mintmark_quality_path
    paths: list[Path] = []
    if configured is not None:
        paths.append(configured)

    paths.extend(DEFAULT_MINTMARK_QUALITY_PATHS)
    return paths


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def _extra_data_path() -> Path:
    return _resolve_path(plugin_config.seer_query_extra_data_path)


def _connect_extra_data() -> sqlite3.Connection:
    path = _extra_data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MINTMARK_QUALITY_TABLE} (
            mintmark_id INTEGER PRIMARY KEY,
            quality INTEGER NOT NULL,
            source TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    return conn


def _load_mintmark_quality_db() -> dict[int, int]:
    path = _extra_data_path()
    if not path.exists():
        return {}

    try:
        with _connect_extra_data() as conn:
            rows = conn.execute(
                f"SELECT mintmark_id, quality FROM {MINTMARK_QUALITY_TABLE}"
            ).fetchall()
    except sqlite3.DatabaseError:
        logger.exception("failed to load mintmark quality cache: {}", path)
        return {}

    quality_map: dict[int, int] = {}
    for row in rows:
        mintmark_id = _coerce_quality(row["mintmark_id"])
        quality = _coerce_quality(row["quality"])
        if mintmark_id is not None and quality is not None:
            quality_map[mintmark_id] = quality

    if quality_map:
        logger.info(
            "loaded mintmark quality cache: {} rows from {}",
            len(quality_map),
            path,
        )
    return quality_map


def _write_mintmark_quality_db(
    quality_map: dict[int, int],
    *,
    source: str,
) -> None:
    if not quality_map:
        return

    path = _extra_data_path()
    now = datetime.now(timezone.utc).timestamp()
    try:
        with _connect_extra_data() as conn:
            conn.executemany(
                f"""
                INSERT INTO {MINTMARK_QUALITY_TABLE}
                    (mintmark_id, quality, source, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(mintmark_id) DO UPDATE SET
                    quality = excluded.quality,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                [
                    (mintmark_id, quality, source, now)
                    for mintmark_id, quality in quality_map.items()
                ],
            )
            conn.commit()
    except sqlite3.DatabaseError:
        logger.exception("failed to write mintmark quality cache: {}", path)


def _mintmark_records(data: object) -> list[object]:
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for container_key, item_key in (
        ("MintMarks", "MintMark"),
        ("mint_marks", "mint_mark"),
    ):
        container = data.get(container_key)
        if isinstance(container, dict):
            records = container.get(item_key)
            if isinstance(records, list):
                return records

    records = data.get("MintMark") or data.get("mint_mark")
    return records if isinstance(records, list) else []


def _load_mintmark_quality_json_map() -> dict[int, int]:
    configured = plugin_config.seer_query_mintmark_quality_path
    for raw_path in _configured_mintmark_quality_paths():
        path = _resolve_path(raw_path)
        if not path.exists():
            if configured is not None and raw_path == configured:
                logger.warning("mintmark quality config not found: {}", path)
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("failed to load mintmark quality config: {}", path)
            continue

        quality_map: dict[int, int] = {}
        for record in _mintmark_records(data):
            if not isinstance(record, dict):
                continue
            mintmark_id = next(
                (
                    coerced_id
                    for key in MINTMARK_ID_KEYS
                    if (coerced_id := _coerce_quality(record.get(key))) is not None
                ),
                None,
            )
            quality = next(
                (
                    coerced_quality
                    for key in MINTMARK_QUALITY_KEYS
                    if (coerced_quality := _coerce_quality(record.get(key)))
                    is not None
                ),
                None,
            )
            if mintmark_id is None or quality is None:
                continue
            quality_map[mintmark_id] = quality

        if quality_map:
            logger.info(
                "loaded mintmark quality config: {} rows from {}",
                len(quality_map),
                path,
            )
            return quality_map

    return {}


def _skip_optional_int_array(reader: _BytesReader) -> None:
    if not reader.read_bool():
        return

    count = reader.read_i32()
    for _ in range(count):
        reader.read_i32()


def _parse_mintmark_quality_item(reader: _BytesReader) -> tuple[int | None, int | None]:
    _skip_optional_int_array(reader)  # Arg
    _skip_optional_int_array(reader)  # BaseAttriValue
    reader.read_i32()  # Connect
    reader.read_text()  # Des
    reader.read_text()  # EffectDes
    _skip_optional_int_array(reader)  # ExtraAttriValue
    reader.read_i32()  # Grade
    reader.read_i32()  # Hide
    mintmark_id = _coerce_quality(reader.read_i32())  # ID
    reader.read_i32()  # Level
    reader.read_i32()  # Max
    _skip_optional_int_array(reader)  # MaxAttriValue
    reader.read_i32()  # MintmarkClass
    _skip_optional_int_array(reader)  # MonsterID
    _skip_optional_int_array(reader)  # MoveID
    quality = _coerce_quality(reader.read_i32())  # Quality
    reader.read_i32()  # Rare
    reader.read_i32()  # Rarity
    reader.read_i32()  # TotalConsume
    reader.read_i32()  # Type
    return mintmark_id, quality


def _parse_mintmark_quality_bytes(data: bytes) -> dict[int, int]:
    if not data:
        return {}

    reader = _BytesReader(data)
    if not reader.read_bool():
        return {}

    quality_map: dict[int, int] = {}
    if reader.read_bool():
        count = reader.read_i32()
        for _ in range(count):
            mintmark_id, quality = _parse_mintmark_quality_item(reader)
            if mintmark_id is not None and quality is not None:
                quality_map[mintmark_id] = quality

    if reader.read_bool():
        class_count = reader.read_i32()
        for _ in range(class_count):
            reader.read_text()
            reader.read_i32()

    return quality_map


def _parse_mintmark_quality_bundle(bundle_data: bytes) -> dict[int, int]:
    text_assets = _extract_text_assets(bundle_data, {MINTMARK_BYTES_NAME})
    return _parse_mintmark_quality_bytes(text_assets.get(MINTMARK_BYTES_NAME, b""))


async def _fetch_mintmark_quality_map() -> dict[int, int]:
    base_url = plugin_config.seer_query_config_package_base_url.rstrip("/") + "/"
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        version_url = f"{base_url}PackageManifest_{PACKAGE_NAME}.version"
        version_response = await client.get(version_url)
        version_response.raise_for_status()
        version = version_response.text.strip()

        manifest_url = f"{base_url}PackageManifest_{PACKAGE_NAME}_{version}.bytes"
        manifest_response = await client.get(manifest_url)
        manifest_response.raise_for_status()
        bundle = _find_config_bundle(manifest_response.content)

        bundle_response = await client.get(f"{base_url}{bundle.file_hash}")
        bundle_response.raise_for_status()

    quality_map = await asyncio.to_thread(
        _parse_mintmark_quality_bundle,
        bundle_response.content,
    )
    if quality_map:
        logger.info(
            "fetched mintmark quality config version {}: {} rows",
            version,
            len(quality_map),
        )
    return quality_map


async def _ensure_mintmark_quality_map(*, fetch_remote: bool) -> dict[int, int]:
    global _MINTMARK_QUALITY_MAP  # noqa: PLW0603

    if not _MINTMARK_QUALITY_MAP:
        async with _MINTMARK_QUALITY_LOCK:
            if not _MINTMARK_QUALITY_MAP:
                quality_map = _load_mintmark_quality_db()
                if not quality_map:
                    quality_map = _load_mintmark_quality_json_map()
                    if quality_map:
                        _write_mintmark_quality_db(
                            quality_map,
                            source="mintmark.json",
                        )
                if not quality_map and fetch_remote:
                    try:
                        quality_map = await _fetch_mintmark_quality_map()
                    except (
                        AttributeError,
                        ImportError,
                        KeyError,
                        OSError,
                        TypeError,
                        ValueError,
                        httpx.HTTPError,
                        struct.error,
                    ):
                        logger.exception("failed to fetch mintmark quality config")
                        quality_map = {}
                    if quality_map:
                        _write_mintmark_quality_db(
                            quality_map,
                            source="ConfigPackage",
                        )
                if quality_map:
                    _MINTMARK_QUALITY_MAP = quality_map

    return _MINTMARK_QUALITY_MAP or {}


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
    quality_map = await _ensure_mintmark_quality_map(
        fetch_remote=command.scope == "five",
    )
    mintmarks = _load_mintmarks(session)
    items = _collect_rank_items(mintmarks, command, quality_map)
    await finish_event_reply(
        matcher,
        event,
        _build_stat_rank_message(command, items),
    )
