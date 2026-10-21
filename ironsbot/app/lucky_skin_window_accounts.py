# SPDX-License-Identifier: MIT
"""Compose lucky-window service accounts from configured QQ identities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.platform import ActorRef, Platform
from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowAccount

if TYPE_CHECKING:
    from ironsbot.config.models.seer_lucky import LuckySkinWindowConfig
    from ironsbot.config.qq_references import QQReferenceResolver
    from ironsbot.services.identity.player_accounts import PlayerAccountRegistry


def build_lucky_skin_window_accounts(
    config: LuckySkinWindowConfig,
    references: QQReferenceResolver,
    player_accounts: PlayerAccountRegistry,
) -> tuple[LuckySkinWindowAccount, ...]:
    """Resolve configured QQ identity references before the service is composed."""

    return tuple(
        LuckySkinWindowAccount(
            actor=ActorRef(
                Platform.ONEBOT,
                str(
                    references.resolve_user(
                        configured.user,
                        location=(f"seer.lucky_skin_window.accounts[{index}].user"),
                    )
                ),
            ),
            player_account=player_accounts.resolve(
                configured.account,
                location=(f"seer.lucky_skin_window.accounts[{index}].account"),
            ),
            watched_skin_ids=tuple(configured.watched_skin_ids),
        )
        for index, configured in enumerate(config.accounts)
    )
