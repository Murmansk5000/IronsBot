# SPDX-License-Identifier: MIT
"""Feature names shared by configuration and platform-neutral services."""

from __future__ import annotations

from enum import Enum
from typing import Final


class Feature(str, Enum):
    ABOUT = "about"
    ADMIN_NOTICE = "admin_notice"
    AI_CHAT = "ai_chat"
    AI_INTENT = "ai_intent"
    AI_INTENT_FIRE_MANUAL = "ai_intent_fire_manual"
    AI_INTENT_TEAM_RECOMMEND = "ai_intent_team_recommend"
    BILI_PUSH = "bili_push"
    BILI_QUERY = "bili_query"
    BLACKLIST = "blacklist"
    FIRE_MANUAL_AD = "fire_manual_ad"
    HELP = "help"
    IMAGE = "image"
    LUCKY_SKIN_WINDOW = "lucky_skin_window"
    MEETING = "meeting"
    PET_CONFIG = "pet_config"
    PLAYER_LINEUP_PRIVATE = "player_lineup_private"
    QQ_OFFICIAL_IDENTITY_INFO = "qq_official_identity_info"
    SEER = "seer"
    SEER_ACTIVITY_PUSH = "seer_activity_push"
    SEER_ACTIVITY_QUERY = "seer_activity_query"
    SEER_AUTOCARD = "seer_autocard"
    SEER_DATA = "seer_data"
    SEER_EQUIPMENT = "seer_equipment"
    SEER_MINTMARK = "seer_mintmark"
    SEER_PEAK = "seer_peak"
    SEER_PET = "seer_pet"
    SEER_PLAYER = "seer_player"
    SEER_RANK = "seer_rank"
    SEER_TEAM = "seer_team"
    SEER_TYPE = "seer_type"
    SEERINFO = "seerinfo"
    SERVER_STATUS_QUERY = "server_status_query"
    TEAM_AUDIT = "team_audit"
    TEAM_RESOURCE_SUBSCRIPTION = "team_resource_subscription"
    TEXT = "text"
    TEXT_PUSH = "text_push"
    WEB_ACTIVITY_LINK = "web_activity_link"
    WEB_ACTIVITY_PUSH = "web_activity_push"


FIRE_MANUAL_AD_FEATURE: Final = Feature.FIRE_MANUAL_AD.value
FIRE_MANUAL_INTENT_FEATURE: Final = Feature.AI_INTENT_FIRE_MANUAL.value
FEATURE_KEYS: Final[frozenset[str]] = frozenset(feature.value for feature in Feature)

SEER_FEATURES: Final[frozenset[str]] = frozenset(
    {
        Feature.SEER_PLAYER.value,
        Feature.SEER_TEAM.value,
        Feature.SEER_PET.value,
        Feature.SEER_MINTMARK.value,
        Feature.SEER_EQUIPMENT.value,
        Feature.SEER_TYPE.value,
        Feature.SEER_PEAK.value,
        Feature.SEER_AUTOCARD.value,
        Feature.SEER_RANK.value,
        Feature.SEER_DATA.value,
    }
)
