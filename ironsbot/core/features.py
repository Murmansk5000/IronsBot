# SPDX-License-Identifier: MIT
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
    FIRE_MANUAL_AD = "fire_manual_ad"
    HELP = "help"
    IMAGE = "image"
    MEETING = "meeting"
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
    SERVER_STATUS_PUSH = "server_status_push"
    SERVER_STATUS_QUERY = "server_status_query"
    TEAM_AUDIT = "team_audit"
    TEAM_RESOURCE_SUBSCRIPTION = "team_resource_subscription"
    TEXT = "text"
    TEXT_PUSH = "text_push"
    WEB_ACTIVITY_LINK = "web_activity_link"
    WEB_ACTIVITY_PUSH = "web_activity_push"


FIRE_MANUAL_AD_FEATURE: Final = Feature.FIRE_MANUAL_AD.value
FIRE_MANUAL_INTENT_FEATURE: Final = Feature.AI_INTENT_FIRE_MANUAL.value
FEATURE_KEYS: Final[frozenset[str]] = frozenset(
    feature.value for feature in Feature
)

SEER_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "seer_player",
        "seer_team",
        "seer_pet",
        "seer_mintmark",
        "seer_equipment",
        "seer_type",
        "seer_peak",
        "seer_autocard",
        "seer_rank",
        "seer_data",
    }
)

FEATURE_BUNDLES: Final[dict[str, frozenset[str]]] = {
    "all": (FEATURE_KEYS - {"admin_notice", "seer"}) | SEER_FEATURES,
    "seer": SEER_FEATURES,
    "query": frozenset(
        {
            *SEER_FEATURES,
            "image",
            "bili_query",
            "seer_activity_query",
            "server_status_query",
        }
    ),
    "bili": frozenset({"bili_query", "bili_push"}),
    "activity": frozenset({"seer_activity_query", "seer_activity_push"}),
    "seer_activity": frozenset({"seer_activity_query", "seer_activity_push"}),
    "server_status": frozenset({"server_status_query", "server_status_push"}),
    "text": frozenset({"text", "web_activity_link", "seerinfo"}),
    "text_push": frozenset({"text_push", "web_activity_push"}),
    "message": frozenset(
        {
            "text",
            "text_push",
            "web_activity_link",
            "web_activity_push",
            "seerinfo",
            "team_audit",
            "team_resource_subscription",
            "ai_intent_team_recommend",
        }
    ),
}

REGISTERED_FEATURE_KEYS: Final[frozenset[str]] = (
    FEATURE_KEYS | frozenset(FEATURE_BUNDLES)
)

__all__ = [
    "FEATURE_BUNDLES",
    "FEATURE_KEYS",
    "FIRE_MANUAL_AD_FEATURE",
    "FIRE_MANUAL_INTENT_FEATURE",
    "REGISTERED_FEATURE_KEYS",
    "SEER_FEATURES",
    "Feature",
]
