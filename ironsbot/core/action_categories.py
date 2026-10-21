# SPDX-License-Identifier: MIT
"""Explicit business-action categories shared by both transports and extensions."""

from enum import Enum


class RequestCategory(str, Enum):
    TAOMEE = "taomee"
    LOCAL = "local"
    OTHER_NETWORK = "other_network"


# Families here are owned registration namespaces, not guesses based on I/O.
_LOCAL_FAMILIES = (
    "messaging.",
    "seer.data.",
    "seer.player.identity.",
    "seer.lucky_skin_window.watch.",
    "message.",
    "sendpic.",
    "seer_data_",
    "seer_new_",
)
_NETWORK_FAMILIES = ("ai_intent.",)
_TAOMEE_FAMILIES = ("seer.rank.player.",)
_LOCAL_ACTIONS = frozenset(
    {
        "help",
        "about",
        "selection_prompt",
        "pet_config",
        "pet_config.query",
        "sendpic",
        "meeting",
        "fire_manual_ad",
        "seer_player_binding",
        "seer_player_unbinding",
        "seer.player.bind",
        "seer.player.unbind",
        "seer.pet.query",
        "seer.pet.avatar",
        "seer.pet.image",
        "seer.pet.flip",
        "seer.mintmark.query",
        "seer.mintmark.rank",
        "seer.equipment.query",
        "seer.type.query",
        "seer.autocard.query",
        "seer.autocard.sanctuary",
        "seer_pet_info",
        "seer_pet_avatar",
        "seer_pet_image",
        "seer_mintmark_query",
        "seer_gem_query",
        "seer_type_query",
        "seer_battle_effect_query",
        "seer_suit_query",
        "seer_equip_query",
        "seer_title_query",
        "seer_equipment_query",
        "seer.pet.skill",
        "about.official_identity_info",
        "rank.help",
        "rank.display_limit",
        "rank.sample_collection",
        "rank.sample_peak",
        "rank.sample_status",
        "rank.page_status",
        "team_resource.subscribe",
        "team_resource.unsubscribe",
        "team_resource.list",
        "bilibili.accounts",
        "bilibili.push_mode",
        "bilibili.private_push_mode",
        "docker_update.restart",
        "server_status.headless_instances",
        "server_status.usage",
        "headless_instance_status",
        "identity_link_begin",
        "identity_link_revoke",
        "identity_link_status",
        "pet_flip",
        "bili_accounts",
        "bili_push_mode",
        "bot_restart",
        "seer_autocard_query",
        "seer_autocard_sanctuary_query",
        "seer_countermark_stat_rank",
        "seer_rank_cache_status",
        "seer_rank_display_limit",
        "seer_rank_help",
        "seer_rank_page_cache_status",
        "seer_season_countdown",
        "team_resource_manage",
    }
)
_TAOMEE_ACTIONS = frozenset(
    {
        "seer_player",
        "seer.player.query",
        "seer.player.default",
        "seer.player.info",
        "seer.player.collection",
        "seer.player.peak",
        "seer.player.autocard",
        "seer.player.beast_rank",
        "seer.player.lineup",
        "player_lineup",
        "player_team",
        "private_player_lineup",
        "private_player_lineup.query",
        "player_lineup_private",
        "seer.team.query",
        "seer_team",
        "seer.peak.query",
        "seer.peak.rank",
        "seer.lucky_skin_window.query",
        "rank.global_collection",
        "rank.global_peak",
        "rank.sample_refresh",
        "rank.page_refresh",
        "rank.page_batch",
        "team_resource.query",
        "team_resource_query",
        "seer_rank_cache_batch",
        "seer_rank_cache_refresh",
        "seer_rank_page_cache_refresh",
        "seer_rank_list",
        "seer_rank_player",
        "seer_rank_score",
        "seer_peak_pool",
        "seer_peak_expert_pool",
        "seer_peak_master_pool",
        "seer_peak_vote",
        "seer_peak_suit_rank",
        "seer_peak_title_rank",
        "seer_peak_pet_rank",
    }
)
_NETWORK_ACTIONS = frozenset(
    {
        "ai_chat",
        "ai_chat.group",
        "ai_chat.private",
        "ai_intent",
        "bilibili",
        "bilibili.dynamic",
        "bilibili.refresh",
        "db_sync",
        "db_sync.update",
        "db_sync.force_update",
        "docker_update",
        "docker_update.image_update",
        "docker_update.image_check",
        "server_status",
        "server_status.query",
        "server_status.admin_query",
        "activity",
        "activity.current",
        "activity.ending",
        "activity.new",
        "bili_query",
        "bili_refresh",
        "data_sync",
        "server_status_admin",
        "server_status_query",
        "seer_activity_current",
        "seer_activity_ending",
        "seer_activity_new",
    }
)


def category_for_action(action_id: str) -> RequestCategory:
    """Reject unclassified actions instead of silently applying a default."""
    if action_id in _LOCAL_ACTIONS or action_id.startswith(_LOCAL_FAMILIES):
        return RequestCategory.LOCAL
    if action_id in _TAOMEE_ACTIONS or action_id.startswith(_TAOMEE_FAMILIES):
        return RequestCategory.TAOMEE
    if action_id in _NETWORK_ACTIONS or action_id.startswith(_NETWORK_FAMILIES):
        return RequestCategory.OTHER_NETWORK
    msg = f"semantic action requires an explicit category: {action_id}"
    raise ValueError(msg)
