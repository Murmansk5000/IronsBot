# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from ironsbot.core.bilibili import (
    SEER_DYNAMIC_CATEGORIES,
    BiliSeerCategoryConfig,
    SeerDynamicCategory,
)
from ironsbot.services.bilibili.parser import dynamic_classification_text

SEER_CATEGORY_LABELS: dict[SeerDynamicCategory, str] = {
    "lottery": "抽奖/中奖",
    "version_preview": "版本预告",
    "version_guide": "版本上线/更新指引",
    "pet": "新精灵",
    "skin": "新皮肤",
    "skill_showcase": "技能特效抢先看",
    "autocard": "群星牌",
    "competition": "赛事直播",
    "story": "主线剧情",
    "event": "联动活动",
    "interaction": "互动征集",
    "other": "其他",
}
SEER_CATEGORY_SUBMENU_PREFIX = "bili_seer_categories:"
SEER_CATEGORY_OPTION_PREFIX = "bili_seer_category:"


def seer_category_submenu_key(uid: int) -> str:
    return f"{SEER_CATEGORY_SUBMENU_PREFIX}{uid}"


def seer_category_option_key(uid: int, category: SeerDynamicCategory) -> str:
    return f"{SEER_CATEGORY_OPTION_PREFIX}{uid}:{category}"


def parse_seer_category_option_key(
    key: str,
) -> tuple[int, SeerDynamicCategory] | None:
    if not key.startswith(SEER_CATEGORY_OPTION_PREFIX):
        return None
    raw_uid, separator, raw_category = key[
        len(SEER_CATEGORY_OPTION_PREFIX) :
    ].partition(":")
    if not separator or raw_category not in SEER_DYNAMIC_CATEGORIES:
        return None
    try:
        uid = int(raw_uid)
    except ValueError:
        return None
    return uid, cast("SeerDynamicCategory", raw_category)


def classify_seer_dynamic(
    item: dict[str, Any],
    *,
    pub_ts: int,
    config: BiliSeerCategoryConfig,
) -> tuple[SeerDynamicCategory, ...]:
    content = dynamic_classification_text(item).strip()
    categories = [
        category
        for category, patterns in config.category_patterns().items()
        if any(
            re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
            for pattern in patterns
        )
    ]
    if "version_preview" not in categories and _matches_preview_window(
        content, pub_ts, config
    ):
        categories.append("version_preview")
    if not categories:
        return ("other",)
    return tuple(
        category for category in SEER_DYNAMIC_CATEGORIES if category in categories
    )


def _matches_preview_window(
    content: str,
    pub_ts: int,
    config: BiliSeerCategoryConfig,
) -> bool:
    if not content or not any(
        re.search(pattern, content, flags=re.IGNORECASE | re.DOTALL)
        for pattern in config.preview_window_patterns
    ):
        return False
    local_time = datetime.fromtimestamp(pub_ts, tz=ZoneInfo(config.timezone))
    current_time = local_time.strftime("%H:%M")
    weekday = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[local_time.weekday()]
    return any(
        weekday in window.weekdays and window.start <= current_time < window.end
        for window in config.preview_windows
    )
