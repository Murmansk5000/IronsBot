# SPDX-License-Identifier: MIT
"""Resolve trusted Tencent union evidence into shared business principals."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.platform import Platform, reference_digest
from ironsbot.services.identity_link_store import (
    OfficialIdentity,
    UnionIdentityConflictError,
    UnionIdentityEvidenceChangedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.platform import IncomingMessageRef
    from ironsbot.services.identity_link_store import (
        CrossPlatformIdentityLink,
        IdentityLinkStore,
    )
    from ironsbot.services.identity_principals import IdentityPrincipalService
    from ironsbot.services.messaging.admin_notice import AdminNoticeService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OfficialUnionIdentityService:
    store: IdentityLinkStore
    admin_notices: AdminNoticeService
    principals: IdentityPrincipalService
    on_link: Callable[[CrossPlatformIdentityLink], None]
    clock: Callable[[], float] = time.time

    async def observe(self, incoming: IncomingMessageRef) -> bool:
        evidence = incoming.official_union_identity
        actor = incoming.actor
        if (
            evidence is None
            or actor.platform is not Platform.QQ_OFFICIAL
            or actor.account_id is None
        ):
            return False
        official = OfficialIdentity(
            actor.account_id,
            actor.kind,
            actor.id,
            actor.scope_id or "",
        )
        try:
            links = await self.store.observe_union_identity(
                official=official,
                union_identity=evidence,
                now=self.clock(),
            )
        except (UnionIdentityConflictError, UnionIdentityEvidenceChangedError) as error:
            await self._report_conflict(incoming, error)
            return False
        self.principals.observe_union_identity(actor=actor, evidence=evidence)
        for link in links:
            self.principals.register_identity_link(link)
            self.on_link(link)
        return bool(links)

    async def _report_conflict(
        self,
        incoming: IncomingMessageRef,
        error: UnionIdentityConflictError | UnionIdentityEvidenceChangedError,
    ) -> None:
        actor = incoming.actor
        account = actor.account_id or "missing"
        logger.error(
            "QQ Official union identity conflict: account=%s actor=%s error_type=%s",
            reference_digest(account),
            reference_digest(actor.id),
            type(error).__name__,
        )
        await self.admin_notices.send(
            "⚠️ QQ 官方统一身份关联冲突\n"
            "已拒绝自动合并，不会覆盖现有账号关联。\n"
            f"账号摘要：{reference_digest(account)}\n"
            f"用户摘要：{reference_digest(actor.id)}\n"
            "请检查身份关联审计记录。",
            subscription_key=(
                "official_union_identity_conflict:"
                f"{reference_digest(account)}:{reference_digest(actor.id)}"
            ),
            action_name="QQ 官方统一身份冲突告警",
        )
