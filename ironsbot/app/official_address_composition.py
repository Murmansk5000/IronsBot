# SPDX-License-Identifier: MIT
"""Connect address evidence to private preferences and Bilibili routing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.integrations.storage.official_addresses import SqliteOfficialAddressStore
from ironsbot.services.official_addresses import OfficialAddressService

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.settings import Settings
    from ironsbot.services.bilibili.targets import BiliTargetService
    from ironsbot.services.identity_link_store import CrossPlatformIdentityLink
    from ironsbot.services.identity_principals import (
        ConversationPrincipalMerge,
        IdentityPrincipalService,
    )


def build_official_addresses(
    settings: Settings,
    principals: IdentityPrincipalService,
    targets: BiliTargetService,
    merge_conversation: Callable[[ConversationPrincipalMerge], None],
) -> OfficialAddressService:
    def register(link: CrossPlatformIdentityLink) -> None:
        for merge in principals.register_private_link(link):
            merge_conversation(merge)
        targets.private_routes.register(link)

    def unregister(link: CrossPlatformIdentityLink) -> None:
        principals.unregister_private_link(link)
        targets.private_routes.unregister(link)

    service = OfficialAddressService(
        SqliteOfficialAddressStore(settings.paths.qq_state),
        principals,
        register,
        unregister,
    )
    accounts = settings.bot.qq_official.enabled_accounts
    for target in settings.identities.users.values():
        for alias, openid in target.official.items():
            if (account := accounts.get(alias)) is not None:
                service.configure_private(account.app_id, openid)
    return service
