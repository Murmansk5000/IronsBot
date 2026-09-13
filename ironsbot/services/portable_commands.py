# SPDX-License-Identifier: MIT
"""Small platform-neutral command surface used during adapter bring-up."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.commands import normalize_command_text
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.about import about_command_contracts
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.about import AboutService
    from ironsbot.services.seer.data_queries import DataQueryReply


class PortableOperation(Protocol):
    def __call__(self) -> Awaitable[OutboundMessage | str | DataQueryImageReply]: ...


class PortableDataQueries(Protocol):
    async def data_version(self) -> DataQueryReply: ...

    async def season_countdown(self) -> DataQueryReply: ...

    async def weekly_preview(self) -> DataQueryReply: ...


@dataclass(frozen=True, slots=True)
class PortableCommandRoute:
    id: str
    examples: tuple[str, ...]
    description: str
    feature: str
    operation: PortableOperation


class PortableCommandRouter:
    """Dispatch stateless commands without importing a platform adapter."""

    def __init__(
        self,
        routes: tuple[PortableCommandRoute, ...],
        features: FeatureService,
    ) -> None:
        self._routes = routes
        self._features = features

    def recognizes(
        self,
        text: str,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> bool:
        command = _command_text(text)
        return command == "帮助" or any(
            command in route.examples
            and self._features.is_feature_allowed(
                actor,
                conversation,
                route.feature,
            )
            for route in self._routes
        )

    async def dispatch(  # noqa: PLR0911
        self,
        text: str,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> OutboundMessage | None:
        command = _command_text(text)
        if command == "帮助":
            if not self._features.is_feature_allowed(
                actor,
                conversation,
                "help",
            ):
                return None
            return self._help(actor=actor, conversation=conversation)
        route = next(
            (
                candidate
                for candidate in self._routes
                if command in candidate.examples
                and self._features.is_feature_allowed(
                    actor,
                    conversation,
                    candidate.feature,
                )
            ),
            None,
        )
        if route is None:
            return None
        try:
            result = await route.operation()
        except DataUnavailableError:
            return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
        if isinstance(result, OutboundMessage):
            return result
        if isinstance(result, DataQueryImageReply):
            return result.to_outbound()
        return OutboundMessage.from_text(result)

    def _help(
        self,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> OutboundMessage:
        routes = tuple(
            route
            for route in self._routes
            if self._features.is_feature_allowed(
                actor,
                conversation,
                route.feature,
            )
        )
        lines = ["【机器人调试功能】", "帮助 - 查看当前可用功能"]
        lines.extend(
            f"{route.examples[0]} - {route.description}" for route in routes
        )
        return OutboundMessage.from_text("\n".join(lines))


def build_portable_command_router(
    *,
    about: AboutService,
    data_queries: PortableDataQueries,
    features: FeatureService,
) -> PortableCommandRouter:
    async def about_message() -> OutboundMessage:
        return about.message()

    return PortableCommandRouter(
        (
            PortableCommandRoute(
                id="about",
                examples=about_command_contracts()[0].examples,
                description="查看项目与版本信息",
                feature="about",
                operation=about_message,
            ),
            _data_route(
                "seer.data.version",
                DATA_VERSION_COMMANDS,
                "查看本地赛尔数据版本",
                data_queries.data_version,
            ),
            _data_route(
                "seer.data.season",
                SEASON_COUNTDOWN_COMMANDS,
                "查看赛季时间",
                data_queries.season_countdown,
            ),
            _data_route(
                "seer.data.preview",
                WEEKLY_PREVIEW_COMMANDS,
                "查看下周预告图片",
                data_queries.weekly_preview,
            ),
        ),
        features,
    )


def _data_route(
    route_id: str,
    examples: tuple[str, ...],
    description: str,
    operation: Callable[[], Awaitable[DataQueryReply]],
) -> PortableCommandRoute:
    return PortableCommandRoute(
        id=route_id,
        examples=examples,
        description=description,
        feature="seer_data",
        operation=operation,
    )


def _command_text(text: str) -> str:
    normalized = normalize_command_text(text)
    return (
        normalize_command_text(normalized[1:])
        if normalized.startswith("/")
        else normalized
    )
