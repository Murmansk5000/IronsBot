# SPDX-License-Identifier: GPL-3.0-or-later
"""Stable configuration names and defaults for official-rank exclusions."""

RANK_EXCLUSION_SUPPORTED_KEYS = (
    "图鉴积分",
    "成就点数",
    "精灵图鉴",
    "皮肤图鉴",
    "套装图鉴",
    "部件图鉴",
    "座驾图鉴",
    "刻印图鉴",
    "群星牌",
    "竞技",
    "狂野",
    "专家",
)

# Query routing keeps longer internal keys for these three peak boards. TOML
# uses the player-facing names in RANK_EXCLUSION_SUPPORTED_KEYS.
RANK_EXCLUSION_CONFIG_KEY_BY_RANK = {
    "竞技段位": "竞技",
    "狂野段位": "狂野",
    "专家段位": "专家",
}

# Accounts created for internal Taomee testing share the same registration time.
# They are excluded from every public rank and the local sample.
DEFAULT_TAOMEE_INTERNAL_USER_IDS = (
    389438787,
    963527044,
    961510772,
    914692158,
    962236717,
    960755946,
    930395179,
    964791989,
    960957048,
    962883553,
    963833963,
    963123185,
    963190850,
    961392272,
    960351788,
    964035946,
    963236961,
    961625369,
    51010611,
)

# These are normal players whose pet collection totals are invalid. They remain
# eligible for all other official ranks and local samples.
DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK = {
    "精灵图鉴": (
        75576625,
        563101901,
        941831079,
        129030222,
        962351895,
        569440141,
        141312889,
        674021793,
        163443467,
        960649568,
        206601225,
        925171143,
        810989428,
    )
}
