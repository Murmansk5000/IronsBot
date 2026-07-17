# SPDX-License-Identifier: MIT
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

from ironsbot.shared.messaging.command_cooldown import (
    CommandIdResolver,
    CommandIdSource,
    mark_command_matcher_exempt,
    register_command_matcher,
    setup_command_cooldown_runtime,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State


class CommandCooldownManifestError(ValueError):
    @classmethod
    def invalid_reference(cls, ref: str) -> CommandCooldownManifestError:
        return cls(f"invalid matcher reference: {ref}")


def _state_object_id_resolver(
    state_key: str,
    *,
    prefix: str,
    attribute: str = "id",
    fallback: str | None = None,
) -> CommandIdResolver:
    def _resolver(_event: MessageEvent, state: T_State) -> str | None:
        value = state.get(state_key)
        object_id = str(getattr(value, attribute, "")).strip()
        if object_id:
            return f"{prefix}.{object_id}"
        return fallback

    return _resolver


def _player_shortcut_resolver(
    _event: MessageEvent,
    state: T_State,
) -> str | None:
    command = state.get("_player_shortcut_command")
    kind = str(getattr(command, "kind", "")).strip()
    return f"seer_player_{kind}" if kind else None


def _load_matcher(ref: str) -> type[Matcher]:
    module_name, separator, attribute = ref.partition(":")
    if not separator:
        raise CommandCooldownManifestError.invalid_reference(ref)
    module = import_module(module_name)
    return cast("type[Matcher]", getattr(module, attribute))


def _is_ironsbot_plugin_matcher(matcher: type[Matcher]) -> bool:
    module_name = str(
        getattr(getattr(matcher, "module", None), "__name__", "")
    )
    return module_name.startswith("ironsbot.plugins.")


_COMMAND_MATCHERS: tuple[tuple[str, CommandIdSource], ...] = (
    ("ironsbot.plugins.about:matcher", "about"),
    ("ironsbot.plugins.help:help_cmd", "help"),
    ("ironsbot.plugins.seer.rank_help:rank_help_entry", "seer_rank_help"),
    ("ironsbot.plugins.activity:current_activity_matcher", "seer_activity_current"),
    (
        "ironsbot.plugins.activity:soon_ending_activity_matcher",
        "seer_activity_ending",
    ),
    ("ironsbot.plugins.ai_chat:ai_chat_matcher", "ai_chat"),
    ("ironsbot.plugins.ai_chat:ai_chat_group_at_matcher", "ai_chat"),
    ("ironsbot.plugins.ai_mention_guard:mention_guard_matcher", "ai_mention_guard"),
    (
        "ironsbot.plugins.ai_intent:ai_intent_action_matcher",
        _state_object_id_resolver(
            "_ai_intent_action",
            prefix="ai_intent",
            fallback="ai_intent",
        ),
    ),
    ("ironsbot.plugins.bilibili.commands:dynamic_menu_matcher", "bili_query"),
    ("ironsbot.plugins.bilibili.commands:update_dynamic_matcher", "bili_refresh"),
    ("ironsbot.plugins.bilibili.commands:bili_account_matcher", "bili_accounts"),
    (
        "ironsbot.plugins.bilibili.commands:bili_push_mode_matcher",
        "bili_push_mode",
    ),
    ("ironsbot.plugins.db_sync:manual_sync_matcher", "data_sync"),
    ("ironsbot.plugins.meeting:meeting_matcher", "meeting"),
    (
        "ironsbot.plugins.messaging.matchers:private_command_matcher",
        _state_object_id_resolver(
            "_message_action_private",
            prefix="message_private",
            fallback="message_private",
        ),
    ),
    (
        "ironsbot.plugins.messaging.matchers:group_command_matcher",
        _state_object_id_resolver(
            "_message_action_group",
            prefix="message_group",
            fallback="message_group",
        ),
    ),
    (
        "ironsbot.plugins.server_status.matchers:normal_server_status_matcher",
        "server_status_query",
    ),
    (
        "ironsbot.plugins.server_status.matchers:disabled_bare_admin_status_matcher",
        "server_status_query",
    ),
    (
        "ironsbot.plugins.server_status.matchers:admin_server_status_matcher",
        "server_status_admin",
    ),
    (
        "ironsbot.plugins.server_status.matchers:bot_restart_matcher",
        "bot_restart",
    ),
    (
        "ironsbot.plugins.server_status.matchers:docker_update_matcher",
        "bot_restart",
    ),
    (
        "ironsbot.plugins.team_resource_subscription:team_resource_matcher",
        "team_resource_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.autocard:autocard_matcher",
        "seer_autocard_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.countermark_stat_rank:"
        "countermark_stat_rank_matcher",
        "seer_countermark_stat_rank",
    ),
    (
        "ironsbot.plugins.seer.query.commands.data_queries:preview_matcher",
        "seer_data_preview",
    ),
    (
        "ironsbot.plugins.seer.query.commands.data_queries:data_version_matcher",
        "seer_data_version",
    ),
    (
        "ironsbot.plugins.seer.query.commands.data_queries:season_countdown_matcher",
        "seer_season_countdown",
    ),
    (
        "ironsbot.plugins.seer.query.commands.equipment_queries:suit_matcher",
        "seer_suit_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.equipment_queries:equip_matcher",
        "seer_equipment_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.equipment_queries:title_matcher",
        "seer_title_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.mintmark_queries:mintmark_matcher",
        "seer_mintmark_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.mintmark_queries:gem_matcher",
        "seer_gem_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.peak_queries:peak_pool_matcher",
        "seer_peak_pool",
    ),
    (
        "ironsbot.plugins.seer.query.commands.peak_queries:peak_expert_pool_matcher",
        "seer_peak_expert_pool",
    ),
    (
        "ironsbot.plugins.seer.query.commands.peak_queries:peak_vote_matcher",
        "seer_peak_vote",
    ),
    (
        "ironsbot.plugins.seer.query.commands.peak_queries:peak_suit_matcher",
        "seer_peak_suit_rank",
    ),
    (
        "ironsbot.plugins.seer.query.commands.peak_queries:peak_title_matcher",
        "seer_peak_title_rank",
    ),
    (
        "ironsbot.plugins.seer.query.commands.peak_queries:peak_pet_matcher",
        "seer_peak_pet_rank",
    ),
    (
        "ironsbot.plugins.seer.query.commands.pet_queries:pet_image_matcher",
        "seer_pet_image",
    ),
    (
        "ironsbot.plugins.seer.query.commands.pet_queries:pet_info_matcher",
        "seer_pet_info",
    ),
    (
        "ironsbot.plugins.seer.query.commands.player:player_binding_matcher",
        "seer_player_binding",
    ),
    (
        "ironsbot.plugins.seer.query.commands.player:player_unbind_matcher",
        "seer_player_binding",
    ),
    (
        "ironsbot.plugins.seer.query.commands.player:player_matcher",
        "seer_player",
    ),
    (
        "ironsbot.plugins.seer.query.commands.player_shortcuts:"
        "player_shortcut_matcher",
        _player_shortcut_resolver,
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:rank_help_matcher",
        "seer_rank_help",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:rank_list_matcher",
        "seer_rank_list",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:rank_player_matcher",
        "seer_rank_player",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:rank_score_matcher",
        "seer_rank_score",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:rank_cache_status_matcher",
        "seer_rank_cache_status",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:rank_cache_refresh_matcher",
        "seer_rank_cache_refresh",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:rank_cache_batch_matcher",
        "seer_rank_cache_batch",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:"
        "rank_page_cache_overview_matcher",
        "seer_rank_page_cache_status",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:"
        "rank_page_cache_status_matcher",
        "seer_rank_page_cache_status",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:"
        "rank_page_cache_refresh_matcher",
        "seer_rank_page_cache_refresh",
    ),
    (
        "ironsbot.plugins.seer.query.commands.rank_list:"
        "rank_display_limit_matcher",
        "seer_rank_display_limit",
    ),
    (
        "ironsbot.plugins.seer.query.commands.team:team_matcher",
        "seer_team",
    ),
    (
        "ironsbot.plugins.seer.query.commands.type_queries:type_matcher",
        "seer_type_query",
    ),
    (
        "ironsbot.plugins.seer.query.commands.type_queries:battle_effect_matcher",
        "seer_battle_effect_query",
    ),
)

_EXEMPT_MESSAGE_MATCHERS: tuple[tuple[str, str], ...] = (
    (
        "ironsbot.plugins.messaging.matchers:push_subscription_matcher",
        "second-level subscription toggle conversation",
    ),
    (
        "ironsbot.plugins.messaging.matchers:push_time_matcher",
        "second-level push time conversation",
    ),
    (
        "ironsbot.plugins.red_packet_notice:red_packet_notice_matcher",
        "passive red packet event detection",
    ),
    (
        "ironsbot.plugins.team_resource_subscription:team_resource_manage_matcher",
        "group subscription management",
    ),
    (
        "ironsbot.plugins.team_resource_subscription:team_resource_prompt_matcher",
        "second-level team subscription confirmation",
    ),
    (
        "ironsbot.plugins.seer.query.commands.player:player_invalid_text_matcher",
        "silent invalid player query blocker",
    ),
)

_manifest_registered = False


def setup_command_cooldown_manifest_runtime() -> None:
    global _manifest_registered  # noqa: PLW0603

    if _manifest_registered:
        return
    for matcher_ref, command_id in _COMMAND_MATCHERS:
        register_command_matcher(_load_matcher(matcher_ref), command_id)
    for matcher_ref, reason in _EXEMPT_MESSAGE_MATCHERS:
        mark_command_matcher_exempt(_load_matcher(matcher_ref), reason)
    setup_command_cooldown_runtime(_is_ironsbot_plugin_matcher)
    _manifest_registered = True


__all__ = [
    "CommandCooldownManifestError",
    "setup_command_cooldown_manifest_runtime",
]
