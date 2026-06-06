# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import asyncio
import io
import json
import struct
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import httpx
from nonebot.log import logger

from ..config import plugin_config

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

PACKAGE_NAME = "ConfigPackage"
CONFIG_BUNDLE_NAME = "pgame_configs_bytes"
CONFIG_TEXT_ASSETS = frozenset(
    {
        "skinStorePool.bytes",
        "skin_shop.bytes",
        "itemsTip.bytes",
    }
)
FASHION_TICKET_VALUE = 10
MAX_PRICE_ROWS = 3
SIGNED_BYTE_MAX = 127
SIGNED_BYTE_MOD = 256


@dataclass(frozen=True, slots=True)
class _BundleInfo:
    name: str
    file_hash: str
    file_size: int


@dataclass(frozen=True, slots=True)
class SkinStorePrice:
    skin_id: int
    pool_id: int
    price: int
    original_price: int
    discount_rate: int
    selected_price: int
    ticket_id: int
    ticket_num: int
    start_time: int
    end_time: int


@dataclass(frozen=True, slots=True)
class SkinShopPrice:
    skin_id: int
    resource_id: int
    card_price: int
    diamond_price: int
    original_price: int


@dataclass(frozen=True, slots=True)
class SkinPriceDataset:
    version: str
    fetched_at: float
    store_prices: dict[int, list[SkinStorePrice]]
    shop_prices: dict[int, SkinShopPrice]
    item_tips: dict[int, str]


class _BytesReader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read_bool(self) -> bool:
        value = self._data[self._pos] != 0
        self._pos += 1
        return value

    def read_i8(self) -> int:
        value = self._data[self._pos]
        self._pos += 1
        return value - SIGNED_BYTE_MOD if value > SIGNED_BYTE_MAX else value

    def read_u16(self) -> int:
        value = struct.unpack_from("<H", self._data, self._pos)[0]
        self._pos += 2
        return int(value)

    def read_i32(self) -> int:
        value = struct.unpack_from("<i", self._data, self._pos)[0]
        self._pos += 4
        return int(value)

    def read_u32(self) -> int:
        value = struct.unpack_from("<I", self._data, self._pos)[0]
        self._pos += 4
        return int(value)

    def read_i64(self) -> int:
        value = struct.unpack_from("<q", self._data, self._pos)[0]
        self._pos += 8
        return int(value)

    def read_text(self) -> str:
        length = self.read_u16()
        end = self._pos + length
        value = self._data[self._pos : end].decode("utf-8")
        self._pos = end
        return value


_DATASET: SkinPriceDataset | None = None
_DATASET_LOCK = asyncio.Lock()


async def format_skin_price_lines(
    skin_id: int,
    *,
    existing_card_price: int | None = None,
) -> str:
    if not plugin_config.seer_query_skin_price:
        return ""

    try:
        dataset = await _get_dataset()
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
        logger.exception("failed to load skin price dataset")
        return ""

    return _format_skin_price_lines(
        dataset,
        skin_id,
        existing_card_price=existing_card_price or 0,
    )


async def _get_dataset() -> SkinPriceDataset:
    global _DATASET  # noqa: PLW0603

    if _is_dataset_fresh(_DATASET):
        return _DATASET

    async with _DATASET_LOCK:
        if _is_dataset_fresh(_DATASET):
            return _DATASET

        cached = _load_cache_file()
        if _is_dataset_fresh(cached):
            _DATASET = cached
            return cached

        dataset = await _fetch_dataset()
        _DATASET = dataset
        _write_cache_file(dataset)
        return dataset


def _is_dataset_fresh(dataset: SkinPriceDataset | None) -> bool:
    if dataset is None:
        return False
    ttl = plugin_config.seer_query_skin_price_cache_ttl_seconds
    return ttl > 0 and time.time() - dataset.fetched_at <= ttl


async def _fetch_dataset() -> SkinPriceDataset:
    base_url = plugin_config.seer_query_config_package_base_url.rstrip("/") + "/"
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        version_url = f"{base_url}PackageManifest_{PACKAGE_NAME}.version"
        version_response = await client.get(version_url, params={"t": int(time.time())})
        version_response.raise_for_status()
        version = version_response.text.strip()

        manifest_url = f"{base_url}PackageManifest_{PACKAGE_NAME}_{version}.bytes"
        manifest_response = await client.get(manifest_url)
        manifest_response.raise_for_status()
        bundle = _find_config_bundle(manifest_response.content)

        bundle_response = await client.get(f"{base_url}{bundle.file_hash}")
        bundle_response.raise_for_status()

    dataset = await asyncio.to_thread(
        _parse_bundle_dataset,
        version,
        bundle_response.content,
    )
    logger.info(
        "loaded skin price dataset version {}: {} skin store rows",
        version,
        sum(len(rows) for rows in dataset.store_prices.values()),
    )
    return dataset


def _find_config_bundle(manifest_data: bytes) -> _BundleInfo:
    reader = _BytesReader(manifest_data)
    reader.read_u32()
    reader.read_text()
    reader.read_bool()
    reader.read_bool()
    reader.read_bool()
    reader.read_i32()
    reader.read_text()
    reader.read_text()

    asset_count = reader.read_i32()
    for _ in range(asset_count):
        reader.read_text()
        reader.read_i32()
        depend_count = reader.read_u16()
        for _ in range(depend_count):
            reader.read_i32()

    bundle_count = reader.read_i32()
    bundles: list[_BundleInfo] = []
    for _ in range(bundle_count):
        name = reader.read_text()
        reader.read_u32()
        file_hash = reader.read_text()
        reader.read_text()
        file_size = reader.read_i64()
        reader.read_bool()
        reader.read_i8()
        reference_count = reader.read_u16()
        for _ in range(reference_count):
            reader.read_i32()
        bundles.append(_BundleInfo(name=name, file_hash=file_hash, file_size=file_size))

    for bundle in bundles:
        if bundle.name == CONFIG_BUNDLE_NAME:
            return bundle

    if len(bundles) == 1:
        return bundles[0]

    raise ValueError("ConfigPackage bundle not found")  # noqa: TRY003


def _parse_bundle_dataset(version: str, bundle_data: bytes) -> SkinPriceDataset:
    text_assets = _extract_text_assets(bundle_data, CONFIG_TEXT_ASSETS)
    store_prices = _parse_skin_store_pool(text_assets.get("skinStorePool.bytes", b""))
    shop_prices = _parse_skin_shop(text_assets.get("skin_shop.bytes", b""))
    item_tips = _parse_items_tip(text_assets.get("itemsTip.bytes", b""))
    return SkinPriceDataset(
        version=version,
        fetched_at=time.time(),
        store_prices=store_prices,
        shop_prices=shop_prices,
        item_tips=item_tips,
    )


def _extract_text_assets(bundle_data: bytes, wanted: Iterable[str]) -> dict[str, bytes]:
    import UnityPy

    wanted_names = set(wanted)
    result: dict[str, bytes] = {}
    env = UnityPy.load(io.BytesIO(bundle_data))
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        data = obj.read()
        name = str(data.m_Name)
        normalized_name = name if name.endswith(".bytes") else f"{name}.bytes"
        if normalized_name not in wanted_names:
            continue
        script = data.m_Script
        result[normalized_name] = (
            script
            if isinstance(script, bytes)
            else script.encode("utf-8", "surrogateescape")
        )
        if len(result) == len(wanted_names):
            break

    missing = wanted_names.difference(result)
    if missing:
        logger.warning(
            "skin price config assets missing: {}",
            ", ".join(sorted(missing)),
        )
    return result


def _parse_skin_store_pool(data: bytes) -> dict[int, list[SkinStorePrice]]:
    if not data:
        return {}

    reader = _BytesReader(data)
    result: dict[int, list[SkinStorePrice]] = {}
    if not reader.read_bool():
        return result

    count = reader.read_i32()
    for _ in range(count):
        reader.read_i32()
        price = reader.read_i32()
        original_price = reader.read_i32()
        discount_rate = reader.read_i32()
        end_time = reader.read_i32()
        reader.read_i32()
        selected_price = reader.read_i32()
        reader.read_i32()
        pool_id = reader.read_i32()
        reader.read_i32()
        reader.read_i32()
        reader.read_i32()
        reader.read_i32()
        skin_id = reader.read_i32()
        start_time = reader.read_i32()
        ticket_id = reader.read_i32()
        ticket_num = reader.read_i32()
        item = SkinStorePrice(
            skin_id=skin_id,
            pool_id=pool_id,
            price=price,
            original_price=original_price,
            discount_rate=discount_rate,
            selected_price=selected_price,
            ticket_id=ticket_id,
            ticket_num=ticket_num,
            start_time=start_time,
            end_time=end_time,
        )
        result.setdefault(skin_id, []).append(item)

    return result


def _parse_skin_shop(data: bytes) -> dict[int, SkinShopPrice]:
    if not data:
        return {}

    reader = _BytesReader(data)
    result: dict[int, SkinShopPrice] = {}
    if not reader.read_bool():
        return result
    if not reader.read_bool():
        return result
    if not reader.read_bool():
        return result

    count = reader.read_i32()
    for _ in range(count):
        reader.read_i32()
        card_price = reader.read_i32()
        diamond_price = reader.read_i32()
        skin_id = reader.read_i32()
        reader.read_i32()
        reader.read_text()
        original_price = reader.read_i32()
        reader.read_i32()
        reader.read_i32()
        if reader.read_bool():
            show_count = reader.read_i32()
            for _ in range(show_count):
                reader.read_i32()
        resource_id = reader.read_i32()
        result[skin_id] = SkinShopPrice(
            skin_id=skin_id,
            resource_id=resource_id,
            card_price=card_price,
            diamond_price=diamond_price,
            original_price=original_price,
        )

    return result


def _parse_items_tip(data: bytes) -> dict[int, str]:
    if not data:
        return {}

    reader = _BytesReader(data)
    result: dict[int, str] = {}
    if not reader.read_bool():
        return result
    if not reader.read_bool():
        return result

    count = reader.read_i32()
    for _ in range(count):
        description = reader.read_text()
        item_id = reader.read_i32()
        result[item_id] = description

    return result


def _format_skin_price_lines(
    dataset: SkinPriceDataset,
    skin_id: int,
    *,
    existing_card_price: int,
) -> str:
    lines: list[str] = []
    shop_price = dataset.shop_prices.get(skin_id)
    if shop_price and shop_price.card_price and not existing_card_price:
        lines.append(f"礼卡价格：{shop_price.card_price}")
    if shop_price and shop_price.diamond_price:
        lines.append(_format_shop_price(shop_price))

    store_prices = _choose_store_prices(dataset.store_prices.get(skin_id, []))
    for price in store_prices:
        line = _format_store_price(price)
        if line:
            lines.append(line)

    return "".join(f"{line}\n" for line in _dedupe_lines(lines))


def _format_shop_price(price: SkinShopPrice) -> str:
    if price.original_price and price.original_price != price.diamond_price:
        return f"钻石价格：{price.diamond_price}钻（原价{price.original_price}钻）"
    return f"钻石价格：{price.diamond_price}钻"


def _choose_store_prices(prices: list[SkinStorePrice]) -> list[SkinStorePrice]:
    if not prices:
        return []

    now = int(time.time())
    active = [item for item in prices if _is_time_active(item, now)]
    selected = active or prices
    return sorted(selected, key=lambda item: (item.pool_id, item.skin_id))[
        :MAX_PRICE_ROWS
    ]


def _is_time_active(price: SkinStorePrice, now: int) -> bool:
    start = price.start_time
    end = price.end_time
    return (start <= 0 or start <= now) and (end <= 0 or now <= end)


def _format_store_price(price: SkinStorePrice) -> str:
    if price.price <= 0 and price.selected_price <= 0:
        return ""

    parts: list[str] = []
    if price.price > 0:
        if price.original_price > 0 and price.original_price != price.price:
            parts.append(f"{price.price}钻（原价{price.original_price}钻）")
        else:
            parts.append(f"{price.price}钻")
    if price.selected_price > 0 and price.selected_price != price.price:
        parts.append(f"自选{price.selected_price}钻")
    if price.ticket_num > 0 and price.price > 0:
        ticket_discount = price.ticket_num * FASHION_TICKET_VALUE
        if ticket_discount < price.price:
            minimum = price.price - ticket_discount
            parts.append(f"最多用{price.ticket_num}张风尚券，最低{minimum}钻")
        else:
            parts.append(f"最多用{price.ticket_num}张风尚券，可抵扣{ticket_discount}钻")

    return "幸运橱窗：" + "；".join(parts)


def _dedupe_lines(lines: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
    return result


def _cache_path() -> Path:
    return plugin_config.seer_query_skin_price_cache_path


def _load_cache_file() -> SkinPriceDataset | None:
    path = _cache_path()
    if not path.exists():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SkinPriceDataset(
            version=str(raw["version"]),
            fetched_at=float(raw["fetched_at"]),
            store_prices={
                int(skin_id): [
                    SkinStorePrice(**item) for item in _ensure_list(items)
                ]
                for skin_id, items in raw.get("store_prices", {}).items()
            },
            shop_prices={
                int(skin_id): SkinShopPrice(**item)
                for skin_id, item in raw.get("shop_prices", {}).items()
            },
            item_tips={
                int(item_id): str(description)
                for item_id, description in raw.get("item_tips", {}).items()
            },
        )
    except (KeyError, OSError, TypeError, ValueError):
        logger.exception("failed to read skin price cache: {}", path)
        return None


def _write_cache_file(dataset: SkinPriceDataset) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": dataset.version,
        "fetched_at": dataset.fetched_at,
        "store_prices": {
            str(skin_id): [asdict(item) for item in items]
            for skin_id, items in dataset.store_prices.items()
        },
        "shop_prices": {
            str(skin_id): asdict(item)
            for skin_id, item in dataset.shop_prices.items()
        },
        "item_tips": {
            str(item_id): description
            for item_id, description in dataset.item_tips.items()
        },
    }
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
