# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import dataclass

PLAYER_ID_KEY = "player_id"
PLAYER_CONVERSATION_NAMESPACE = "seer_player"
PLAYER_DETAIL_NAMESPACE = PLAYER_CONVERSATION_NAMESPACE
PLAYER_BINDING_NAMESPACE = PLAYER_CONVERSATION_NAMESPACE
PLAYER_BINDING_PENDING_KEY = "_player_binding_pending"
PLAYER_BINDING_REPLACEMENT_KEY = "_player_binding_replacement"
PLAYER_QUERY_IS_EXPLICIT_KEY = "_player_query_is_explicit"
PLAYER_ERROR_FORMATTER_KEY = "_player_error_formatter"
PLAYER_DETAIL_MENU_CONTEXT_KEY = "_player_detail_menu_context"


@dataclass(frozen=True, slots=True)
class PlayerDetailMenuContext:
    """Stable query capabilities retained by a player-detail menu session."""

    player_id: int
    has_collection: bool
    has_peak: bool
    has_autocard: bool
