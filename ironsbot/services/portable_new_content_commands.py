# SPDX-License-Identifier: MIT
"""Portable weekly release-content menus backed by shared Seer services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.seer.autocard import AutocardEntry
from ironsbot.services.seer.data import (
    DataPublicationChangedError,
    DataUnavailableError,
)
from ironsbot.services.seer.data_query_commands import (
    NEW_CONTENT_COMMAND_SPECS,
    available_new_content_categories,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.new_content import (
    NewContentIndexUnavailableError,
    NewContentSnapshotChangedError,
    new_content_unavailable_message,
)
from ironsbot.services.seer.new_content_menu import (
    NewContentAction,
    NewContentMenuLayout,
    build_new_content_menu,
    focus_new_content_category,
    plan_new_content_menu,
)
from ironsbot.services.seer.query_result import QueryReply

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.data_queries import SeerDataQueryService
    from ironsbot.services.seer.new_content import (
        NewContentCategory,
        NewContentItem,
        NewContentSnapshot,
    )
    from ironsbot.services.seer.resources import SeerQueryResources


def build_portable_new_content_operations(
    resources: SeerQueryResources,
    sessions: PortableQuerySessions,
    features: FeatureService,
    *,
    expanded_categories: frozenset[NewContentCategory] = frozenset(),
    preview_max_items: int = 5,
) -> Mapping[str, PortableOperation]:
    """Expose every catalogued weekly-content command through one owner."""

    owner = _PortableNewContentOperations(
        resources.data_queries,
        resources,
        sessions,
        features,
        expanded_categories,
        preview_max_items,
    )
    return {
        "seer.data.new_content": owner.root,
        **{spec.command_id: owner.focused for spec in NEW_CONTENT_COMMAND_SPECS},
    }


@dataclass(frozen=True, slots=True)
class _PortableNewContentOperations:
    service: SeerDataQueryService
    resources: SeerQueryResources
    sessions: PortableQuerySessions
    features: FeatureService
    expanded_categories: frozenset[NewContentCategory]
    preview_max_items: int

    async def root(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return await self._start(context, None)

    async def focused(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        spec = next(
            (
                candidate
                for candidate in NEW_CONTENT_COMMAND_SPECS
                if text in candidate.commands
            ),
            None,
        )
        if spec is None:
            msg = f"catalog accepted unknown new-content command: {text!r}"
            raise ValueError(msg)
        return await self._start(context, spec.categories)

    async def _start(
        self,
        context: MessageInputContext,
        categories: tuple[NewContentCategory, ...] | None,
    ) -> OutboundMessage:
        try:
            snapshot = self.service.new_content_snapshot()
        except DataUnavailableError:
            return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
        except NewContentIndexUnavailableError:
            return OutboundMessage.from_text(new_content_unavailable_message())

        message = context.message
        available = available_new_content_categories(
            lambda feature: self.features.is_feature_allowed(
                message.actor,
                message.conversation,
                feature,
            )
        )
        layout = plan_new_content_menu(
            snapshot,
            available,
            categories,
            expanded_categories=self.expanded_categories,
            preview_max_items=self.preview_max_items,
        )
        if isinstance(layout, str):
            return OutboundMessage.from_text(layout)
        return await self._offer(context, snapshot, layout)

    async def _offer(
        self,
        context: MessageInputContext,
        snapshot: NewContentSnapshot,
        layout: NewContentMenuLayout,
    ) -> OutboundMessage:
        menu = build_new_content_menu(snapshot, layout)
        try:
            image = await self.resources.new_content_menu(
                snapshot,
                layout.display_categories,
                layout.focused_category,
                "新增内容",
                layout.expanded_categories,
                layout.preview_max_items,
            )
        except (NewContentSnapshotChangedError, DataPublicationChangedError):
            return OutboundMessage.from_text(
                "数据已更新，当前新增内容菜单已失效，重新发送指令查看。"
            )

        async def select(
            action: NewContentAction,
            context: MessageInputContext,
        ) -> OutboundMessage:
            if action.kind == "category":
                return await self._offer(
                    context,
                    snapshot,
                    focus_new_content_category(layout, action.category),
                )
            if action.item is None:
                return OutboundMessage.from_text("当前新增内容没有可展示的详情。")
            return await self._detail(snapshot, action.item, context)

        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=tuple(choice.action for choice in menu.choices),
                labels=tuple(choice.name for choice in menu.choices),
                choice_keys=tuple(
                    str(index) if choice.is_visible else choice.key or ""
                    for index, choice in enumerate(menu.choices, start=1)
                ),
                text_inputs=tuple(
                    frozenset({choice.key}) if choice.key else frozenset()
                    for choice in menu.choices
                ),
                hidden_choice_indexes=frozenset(
                    index
                    for index, choice in enumerate(menu.choices, start=1)
                    if not choice.is_visible
                ),
                select=select,
                prompt=OutboundMessage((BinaryImagePart(image, "image/png"),)),
                keep_open=True,
                shareable=True,
                can_select=lambda action, responder: (
                    action.category
                    in available_new_content_categories(
                        lambda feature: self.features.is_feature_allowed(
                            responder.message.actor,
                            responder.message.conversation,
                            feature,
                        )
                    )
                ),
                exit_message="已退出新增内容查询。",
            ),
        )

    async def _detail(
        self,
        snapshot: NewContentSnapshot,
        item: NewContentItem,
        context: MessageInputContext,
    ) -> OutboundMessage:
        try:
            detail = await self.resources.new_content_details.select(
                snapshot, item, execution_identity=context.execution_identity
            )
        except (NewContentSnapshotChangedError, DataPublicationChangedError):
            return OutboundMessage.from_text(
                "数据已更新，当前新增内容菜单已失效，重新发送指令查看。"
            )
        except DataUnavailableError:
            return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)

        if isinstance(detail, QueryReply):
            return detail.to_outbound()
        if isinstance(detail, AutocardEntry):
            return await self.resources.autocard_media.outbound(
                detail,
                include_additional_images=False,
            )
        if isinstance(detail, str) and detail:
            return OutboundMessage.from_text(detail)
        return OutboundMessage.from_text("当前新增内容没有可展示的详情。")
