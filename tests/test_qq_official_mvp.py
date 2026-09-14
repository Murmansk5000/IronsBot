from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from qqbot_agent_sdk.dto import MSG_TYPE_QUOTE
from qqbot_agent_sdk.event_parser import InboundEvent

from ironsbot.config.loader import load_settings
from ironsbot.config.models.features import FeatureConfig, build_onebot_feature_service
from ironsbot.config.models.settings import (
    QQOfficialAccountConfig,
    QQOfficialConfig,
)
from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    TextPart,
)
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.qq_official.identity import qq_official_incoming_message
from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialTextPayload,
    render_qq_official_outbound_message,
)
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
)
from ironsbot.integrations.qq_official.runtime import (
    deliver_qq_official_reply,
    qq_official_event_is_supported,
    qq_official_event_mentions_bot,
)
from ironsbot.services.about import AboutService, about_command_contracts
from ironsbot.services.activity.command_contracts import activity_command_contracts
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.meeting import meeting_command_contracts
from ironsbot.services.operations.data_sync import (
    ManualDataSyncAction,
    ManualDataSyncOption,
)
from ironsbot.services.operations.data_sync_commands import data_sync_command_contracts
from ironsbot.services.operations.docker_commands import docker_command_contracts
from ironsbot.services.operations.server_status import ServerStatusResult
from ironsbot.services.operations.server_status_commands import (
    server_status_command_contracts,
)
from ironsbot.services.pet_config_commands import pet_config_command_contracts
from ironsbot.services.portable_commands import (
    PortableCommandRouter,
    PortableCommandRouterError,
    build_portable_command_router,
)
from ironsbot.services.portable_reply import PortableReply, progress_operation_reply
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.peak import PeakQueryResult
from ironsbot.services.seer.player_id_resolver import PlayerIdResolution
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult
from ironsbot.services.seer.rank_command_contracts import rank_help_command_contracts

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.integrations.qq_official.message_rendering import QQOfficialPayload
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.identity_link_commands import IdentityLinkCommands
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.server_status import ServerStatusService
    from ironsbot.services.pet_config import PetConfigQueryService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.rank_admin import RankAdminService
    from ironsbot.services.seer.rank_list_models import (
        RankListCommand,
        RankPageCacheStatusCommand,
    )
    from ironsbot.services.seer.resources import SeerQueryResources
    from ironsbot.services.seer.team import TeamQueryActor
    from ironsbot.services.team.resource import TeamResourceService


class _FakeDataQueries:
    async def data_version(self) -> str:
        return "version"

    async def season_countdown(self) -> str:
        return "season"

    async def weekly_preview(self) -> DataQueryImageReply:
        return DataQueryImageReply(b"preview")


class _FakeActivityService:
    async def build_current_message(self, *, soon_only: bool = False) -> str:
        return "快结束活动" if soon_only else "当前活动"

    async def build_newly_added_message(self) -> str:
        return "新增活动"


class _FakeServerStatusService:
    async def query_normal(self) -> ServerStatusResult:
        return ServerStatusResult("normal status")

    async def query_admin(self) -> ServerStatusResult:
        return ServerStatusResult("admin status")

    async def query_headless_instances(self) -> ServerStatusResult:
        return ServerStatusResult("instance status")


class _FakePetConfigService:
    async def search(self, argument: str) -> QueryResult[int]:
        if argument != "雷伊":
            return QueryResult()
        return QueryResult(reply=QueryReply(image=b"pet-config"))

    async def select(self, pet_id: int) -> QueryResult[object]:
        del pet_id
        return QueryResult()


class _FakeRankAdminService:
    def cache_status(self, conversation: ConversationRef | None) -> str:
        assert conversation is not None
        return "sample status"

    def page_overview(self) -> str:
        return "page overview"

    def page_status(self, command: RankPageCacheStatusCommand) -> str:
        return f"page status:{command.rank_key}"

    async def cache_refresh(self, *, actor: ActorRef, progress: object) -> str:
        del actor
        await cast("Callable[[str], Awaitable[None]]", progress)(
            "sample refresh start"
        )
        return "sample refresh done"


class _FakeDataSyncService:
    async def prepare_manual(
        self,
        *,
        force: bool,
        progress: object,
    ) -> tuple[str, bool]:
        await cast("Callable[[str], Awaitable[None]]", progress)("data check start")
        return ("force data menu" if force else "data menu"), True

    @staticmethod
    def manual_options(*, force: bool) -> tuple[ManualDataSyncOption, ...]:
        del force
        return (
            ManualDataSyncOption(
                "1",
                ManualDataSyncAction.SYNC_PUBLISHED,
                "sync published",
            ),
        )

    async def run_manual(
        self,
        *,
        action: ManualDataSyncAction,
        force: bool,
        progress: object,
    ) -> str:
        del action, force
        await cast("Callable[[str], Awaitable[None]]", progress)("data sync start")
        return "data sync done"


class _FakeDockerUpdateService:
    def __init__(self) -> None:
        self.prepared: list[object] = []
        self.executed: list[object] = []

    async def check_image_update(self, *, progress: object) -> str:
        await cast("Callable[[str], Awaitable[None]]", progress)("image check start")
        return "image check done"

    async def prepare_maintenance(self, choice: object) -> tuple[str, object]:
        self.prepared.append(choice)
        return "maintenance prepared", "process"

    async def execute_restart(self, action: object) -> None:
        self.executed.append(action)


class _FakePlayerIdResolver:
    def has_known_reference(self, _value: str, *_context: object) -> bool:
        return False

    def resolve(
        self,
        _context: MessageInputContext,
        reference: str | None,
        *,
        allow_default_binding: bool = True,
    ) -> PlayerIdResolution:
        del allow_default_binding
        return PlayerIdResolution(
            int(reference) if reference and reference.isdecimal() else None,
            offer_binding=bool(reference),
        )


class _UnusedQueryService:
    def __getattr__(
        self,
        _name: str,
    ) -> Callable[..., Awaitable[QueryResult[object]]]:
        async def query(*_args: object, **_kwargs: object) -> QueryResult[object]:
            return QueryResult()

        return query


class _FakePetQuery:
    def __init__(self, *, fail_selection: bool = False) -> None:
        self._fail_selection = fail_selection

    async def search_info(self, _argument: str) -> QueryResult[int]:
        return QueryResult(
            choices=(
                QueryChoice("雷伊", "70", 70),
                QueryChoice("雷神雷伊", "2394", 2394),
            )
        )

    async def select_info(self, pet_id: int) -> QueryResult[object]:
        if self._fail_selection:
            raise DataUnavailableError
        return QueryResult(reply=QueryReply(text=f"精灵:{pet_id}"))

    async def search_image(self, _argument: str) -> QueryResult[int]:
        return QueryResult()

    async def select_image(self, _pet_id: int) -> QueryResult[object]:
        return QueryResult()


class _FakePeakQuery(_UnusedQueryService):
    async def pool(
        self,
        *,
        expert: bool,
        progress: Callable[[str], Awaitable[None]],
    ) -> PeakQueryResult:
        await progress("rendering")
        return PeakQueryResult(text="专家池" if expert else "竞技池")


class _FakeTeamQuery:
    @staticmethod
    def parse_team_ids(text: str) -> tuple[int, ...]:
        return tuple(int(value) for value in text.split())

    async def query(
        self,
        team_ids: tuple[int, ...],
        actor: TeamQueryActor,
    ) -> str:
        assert actor.actor.id == "opaque-member"
        assert actor.conversation is not None
        assert actor.conversation.id == "group-a"
        assert not actor.can_manage
        return "战队:" + ",".join(str(value) for value in team_ids)


class _FakeRankQueries:
    def default_limit(self, _conversation: ConversationRef | None) -> int:
        return 10

    def set_display_limit(
        self,
        *,
        conversation: ConversationRef | None,
        actor: ActorRef,
        can_manage: bool,
        limit: int,
    ) -> str:
        assert conversation is not None
        assert can_manage
        return (
            f"榜单显示:{conversation.account_id}:"
            f"{conversation.id}:{actor.id}:{limit}"
        )

    async def list(
        self,
        command: RankListCommand,
        *,
        actor: ActorRef | None = None,
        conversation: ConversationRef | None = None,
    ) -> str:
        del actor, conversation
        return f"榜单:{command.rank_key}:{command.start_rank}:{command.limit}"


class _FakeAi:
    def __init__(self, reply: str | None = "AI回复") -> None:
        self.reply = reply
        self.calls: list[tuple[ActorRef, ConversationRef, str]] = []

    async def chat_reply(
        self,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
        prompt: str,
        source_context: str | None = None,
    ) -> str | None:
        assert source_context is None
        self.calls.append((actor, conversation, prompt))
        return self.reply


class _FakeOfficialBot:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent = 0
        self.calls: list[tuple[str, str, object, str | None, int | None]] = []

    async def send_to_c2c(
        self,
        openid: str,
        payloads: tuple[QQOfficialPayload, ...],
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object:
        self.calls.append(("private", openid, payloads, msg_id, msg_seq))
        self.sent += 1
        if self.fail:
            raise _TransportError
        return SimpleNamespace(id=f"sent-{self.sent}")

    async def send_to_group(
        self,
        group_openid: str,
        payloads: tuple[QQOfficialPayload, ...],
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> object:
        self.calls.append(("group", group_openid, payloads, msg_id, msg_seq))
        self.sent += 1
        if self.fail:
            raise _TransportError
        return SimpleNamespace(id=f"sent-{self.sent}")


class _TransportError(RuntimeError):
    pass


def _sdk_event(  # noqa: PLR0913 - fixture exposes the SDK event dimensions
    *,
    event_type: str = "C2C_MESSAGE_CREATE",
    chat_scope: str = "c2c",
    chat_id: str = "opaque-user",
    user_id: str = "opaque-user",
    content: str = "about",
    message_type: int = 0,
    raw: dict[str, object] | None = None,
) -> InboundEvent:
    return InboundEvent(
        event_type=event_type,
        chat_id=chat_id,
        user_id=user_id,
        chat_scope=chat_scope,
        content=content,
        message_id="message-id",
        timestamp="2099-01-01T00:00:00+08:00",
        message_type=message_type,
        raw=raw or {},
    )


def _fake_seer(
    *,
    pet_query: object | None = None,
    peak_query: object | None = None,
    team_query: object | None = None,
    rank_queries: object | None = None,
    rank_admin: object | None = None,
) -> SeerQueryResources:
    unused = _UnusedQueryService()
    return cast(
        "SeerQueryResources",
        SimpleNamespace(
            data_queries=_FakeDataQueries(),
            team_query=team_query or unused,
            pet_query=pet_query or unused,
            mintmark=unused,
            equipment=unused,
            type_query=unused,
            battle_effect=unused,
            peak_query=peak_query or unused,
            player=unused,
            rank_queries=rank_queries or unused,
            rank_admin=rank_admin or unused,
        ),
    )


def _unused_team_resource() -> TeamResourceService:
    return cast("TeamResourceService", SimpleNamespace())


async def _unused_identity_operation(
    _text: str,
    _context: MessageInputContext,
) -> OutboundMessage:
    return OutboundMessage.from_text("unused")


def _identity_links() -> IdentityLinkCommands:
    return cast(
        "IdentityLinkCommands",
        SimpleNamespace(
            portable_confirm=_unused_identity_operation,
            portable_status=_unused_identity_operation,
            portable_revoke=_unused_identity_operation,
        ),
    )


def _portable_catalog(  # noqa: PLR0913 - tests vary independent command families
    *,
    ai_chat: bool = False,
    activity: bool = False,
    bilibili: bool = False,
    operations: bool = False,
    maintenance: bool = False,
    pet_config: bool = False,
    rank_display: bool = False,
    rank_status: bool = False,
) -> CommandCatalog:
    command_ids = {
        "seer.data.query",
        "seer.player.query",
        "seer.player.default",
        "seer.player.bind",
        "seer.player.unbind",
        "seer.team.query",
        "seer.pet.query",
        "seer.pet.image",
        "seer.mintmark.query",
        "seer.equipment.query",
        "seer.type.query",
        "seer.peak.query",
        "seer.peak.rank",
        "rank.help",
        "rank.global_collection",
        "rank.global_peak",
        "rank.sample_collection",
        "rank.sample_peak",
    }
    if rank_status:
        command_ids.update(
            (
                "rank.sample_status",
                "rank.sample_refresh",
                "rank.page_status",
                "rank.page_refresh",
                "rank.page_batch",
            )
        )
    if rank_display:
        command_ids.add("rank.display_limit")
    seer_contracts = tuple(
        contract
        for contract in seer_command_contracts(
            cast("PlayerIdResolver", _FakePlayerIdResolver())
        )
        if contract.id in command_ids
    )
    rank_contracts = tuple(
        contract
        for contract in rank_help_command_contracts(
            cast("PlayerIdResolver", _FakePlayerIdResolver())
        )
        if contract.id in command_ids
    )
    catalog = CommandCatalog()
    contributions = [
        PluginContribution(id="help", commands=help_command_contracts()),
        PluginContribution(id="about", commands=about_command_contracts()),
        PluginContribution(id="seer_query", commands=seer_contracts),
        PluginContribution(id="rank_help", commands=rank_contracts),
    ]
    if ai_chat:
        contributions.append(
            PluginContribution(
                id="ai_chat",
                commands=ai_chat_command_contracts(enabled=True),
            )
        )
    if activity:
        contributions.append(
            PluginContribution(id="activity", commands=activity_command_contracts())
        )
    if bilibili:
        contributions.append(
            PluginContribution(
                id="bilibili",
                commands=bilibili_command_contracts(),
            )
        )
    if operations:
        contributions.extend(
            (
                PluginContribution(
                    id="server_status",
                    commands=server_status_command_contracts(),
                ),
                PluginContribution(
                    id="meeting",
                    commands=meeting_command_contracts(("会议",)),
                ),
            )
        )
    if maintenance:
        contributions.extend(
            (
                PluginContribution(
                    id="db_sync",
                    commands=data_sync_command_contracts(),
                ),
                PluginContribution(
                    id="docker_update",
                    commands=docker_command_contracts(),
                ),
            )
        )
    if pet_config:
        contributions.append(
            PluginContribution(
                id="pet_config",
                commands=pet_config_command_contracts(enabled=True),
            )
        )
    catalog.load(
        tuple(contributions),
        known_features=(
            "help",
            "about",
            "seer_data",
            "seer_player",
            "seer_team",
            "seer_pet",
            "seer_mintmark",
            "seer_equipment",
            "seer_type",
            "seer_peak",
            "seer_rank",
            "ai_chat",
            "seer_activity_query",
            "bili_query",
            "bili_push",
            "server_status_query",
            "meeting",
            "pet_config",
        ),
    )
    return catalog


def _portable_input(
    text: str,
    actor: ActorRef,
    conversation: ConversationRef,
    *,
    group_role: str | None = None,
    mentions_bot: bool | None = None,
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform=actor.platform,
            actor=actor,
            conversation=conversation,
            message_id=f"message-{actor.id}-{text}",
            text=text,
            group_role=group_role,
        ),
        mentions_bot=(
            conversation.kind == "group" if mentions_bot is None else mentions_bot
        ),
    )


def _qq_config(  # noqa: PLR0913 - tests vary independent account boundaries
    *,
    features: list[str] | None = None,
    superusers: list[str] | None = None,
    group_policy: dict[str, list[str]] | None = None,
    user_policy: dict[str, list[str]] | None = None,
    group_superusers: dict[str, list[str]] | None = None,
    group_aliases: dict[str, str] | None = None,
    user_aliases: dict[str, str] | None = None,
    proactive_messages: bool = False,
) -> QQOfficialConfig:
    return QQOfficialConfig(
        enabled=True,
        accounts={
            "example_bot": QQOfficialAccountConfig(
                enabled=True,
                app_id="example-app",
                secret="example-secret",
                features=[] if features is None else features,
                superusers=[] if superusers is None else superusers,
                group_policy={} if group_policy is None else group_policy,
                user_policy={} if user_policy is None else user_policy,
                group_superusers=(
                    {} if group_superusers is None else group_superusers
                ),
                group_aliases={} if group_aliases is None else group_aliases,
                user_aliases={} if user_aliases is None else user_aliases,
                proactive_messages=proactive_messages,
            )
        },
    )


def test_qq_official_config_loads_credentials_from_environment(
    tmp_path: Path,
) -> None:
    startup_timeout_seconds = 20.0
    path = tmp_path / "ironsbot.toml"
    path.write_text(
        """
[bot.qq_official]
enabled = true
startup_timeout_seconds = 20.0

[bot.qq_official.accounts.example_bot]
enabled = true
required = true
app_id = "example-app"
custom_keyboards = true
features = ["help", "about", "seer_data"]
superusers = ["opaque-admin"]
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(
        path,
        env={
            "QQ_OFFICIAL_SECRET_EXAMPLE_BOT": "example-secret",
        },
    )

    assert settings.bot.qq_official.enabled
    assert settings.bot.qq_official.startup_timeout_seconds == startup_timeout_seconds
    account = settings.bot.qq_official.accounts["example_bot"]
    assert account.secret == "example-secret"
    assert account.required
    assert account.custom_keyboards
    assert account.superusers == ["opaque-admin"]


def test_qq_official_config_loads_independent_accounts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ironsbot.toml"
    path.write_text(
        """
[bot.qq_official]
enabled = true

[bot.qq_official.accounts.example_a]
enabled = true
app_id = "app-a"
features = ["help"]

[bot.qq_official.accounts.example_b]
enabled = true
app_id = "app-b"
features = ["about"]
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(
        path,
        env={
            "QQ_OFFICIAL_SECRET_EXAMPLE_A": "secret-a",
            "QQ_OFFICIAL_SECRET_EXAMPLE_B": "secret-b",
        },
    )

    accounts = settings.bot.qq_official.enabled_accounts
    actual = [
        (name, account.app_id, account.secret)
        for name, account in accounts.items()
    ]
    assert actual == [
        ("example_a", "app-a", "secret-a"),
        ("example_b", "app-b", "secret-b"),
    ]


def test_qq_official_account_features_are_isolated_by_app_id() -> None:
    config = QQOfficialConfig(
        enabled=True,
        accounts={
            "example_a": QQOfficialAccountConfig(
                enabled=True,
                app_id="app-a",
                secret="secret-a",
                features=["help"],
            ),
            "example_b": QQOfficialAccountConfig(
                enabled=True,
                app_id="app-b",
                secret="secret-b",
                features=["about"],
            ),
        },
    )
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=config,
    )
    actor_a = ActorRef(Platform.QQ_OFFICIAL, "same-openid", account_id="app-a")
    actor_b = ActorRef(Platform.QQ_OFFICIAL, "same-openid", account_id="app-b")

    assert features.is_actor_feature_allowed(actor_a, "help")
    assert not features.is_actor_feature_allowed(actor_a, "about")
    assert features.is_actor_feature_allowed(actor_b, "about")
    assert not features.is_actor_feature_allowed(actor_b, "help")


def test_qq_official_config_exposes_every_enabled_account() -> None:
    config = QQOfficialConfig(
        enabled=True,
        accounts={
            "example_a": QQOfficialAccountConfig(
                enabled=True,
                app_id="app-a",
                secret="secret-a",
            ),
            "example_b": QQOfficialAccountConfig(
                enabled=True,
                app_id="app-b",
                secret="secret-b",
            ),
            "disabled": QQOfficialAccountConfig(
                enabled=False,
                app_id="app-disabled",
            ),
        },
    )

    assert tuple(config.enabled_accounts) == ("example_a", "example_b")
    assert [account.app_id for account in config.enabled_accounts.values()] == [
        "app-a",
        "app-b",
    ]
    assert [account.secret for account in config.enabled_accounts.values()] == [
        "secret-a",
        "secret-b",
    ]


def test_qq_official_config_rejects_duplicate_app_ids() -> None:
    with pytest.raises(ValueError, match="duplicate QQ Official AppID"):
        QQOfficialConfig(
            enabled=True,
            accounts={
                "example_a": QQOfficialAccountConfig(
                    enabled=True,
                    app_id="same-app",
                    secret="secret-a",
                ),
                "example_b": QQOfficialAccountConfig(
                    enabled=True,
                    app_id="same-app",
                    secret="secret-b",
                ),
            },
        )


def test_qq_official_config_rejects_secret_environment_alias_collision() -> None:
    with pytest.raises(ValueError, match="unique ignoring case"):
        QQOfficialConfig(
            accounts={
                "example": QQOfficialAccountConfig(),
                "EXAMPLE": QQOfficialAccountConfig(),
            }
        )


def test_qq_official_config_rejects_old_single_account_fields() -> None:
    with pytest.raises(ValueError, match="app_id"):
        QQOfficialConfig(
            enabled=True,
            app_id="old-app",  # type: ignore[call-arg]
            secret="old-secret",  # type: ignore[call-arg]
        )


def test_qq_official_config_rejects_retired_static_token() -> None:
    with pytest.raises(ValueError, match="token"):
        QQOfficialAccountConfig(
            enabled=True,
            app_id="example-app",
            secret="example-secret",
            token="retired-token",  # type: ignore[call-arg]
        )


def test_team_resource_requires_qq_official_proactive_delivery() -> None:
    with pytest.raises(ValueError, match="proactive_messages must be true"):
        _qq_config(
            features=["team_resource_subscription"],
        )

    config = _qq_config(
        proactive_messages=True,
        features=["team_resource_subscription"],
    )
    assert config.accounts["example_bot"].proactive_messages

    with pytest.raises(ValueError, match="proactive_messages must be true"):
        _qq_config(
            features=[],
            group_policy={
                "opaque-group": ["team_resource_subscription"],
            },
        )


def test_qq_official_openid_policies_feed_shared_feature_service() -> None:
    config = _qq_config(
        features=[],
        group_policy={"opaque-group": ["seer_activity_push"]},
        user_policy={"opaque-user": ["bili_push"]},
    )
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=config,
    )

    assert features.conversations_for_feature("seer_activity_push") == [
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            "opaque-group",
            account_id="example-app",
        )
    ]
    assert features.actors_for_feature("bili_push") == [
        ActorRef(
            Platform.QQ_OFFICIAL,
            "opaque-user",
            account_id="example-app",
        )
    ]


def test_qq_official_aliases_feed_policy_and_superuser_identity() -> None:
    config = _qq_config(
        features=[],
        superusers=["official_admin"],
        group_aliases={"official_group": "opaque-group"},
        user_aliases={"official_admin": "opaque-admin"},
        group_policy={"official_group": ["seer_rank"]},
    )
    features = build_onebot_feature_service(
        FeatureConfig(superuser_bypass=True),
        (),
        qq_official=config,
    )
    admin = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-admin",
        account_id="example-app",
    )
    group = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "opaque-group",
        account_id="example-app",
    )

    assert features.is_actor_superuser(admin)
    assert features.conversation_has_feature(group, "seer_rank")


def test_qq_official_group_member_openid_can_be_a_superuser() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(superuser_bypass=True),
        (),
        qq_official=_qq_config(
            features=[],
            group_aliases={"official_group": "opaque-group"},
            group_superusers={"official_group": ["opaque-member"]},
        ),
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        "member",
        "opaque-group",
        "example-app",
    )

    assert features.is_actor_superuser(member)
    assert features.is_actor_feature_allowed(member, "seer_rank")
    assert not features.is_actor_superuser(
        ActorRef(
            Platform.QQ_OFFICIAL,
            "opaque-member",
            "member",
            "other-group",
            "example-app",
        )
    )
    assert all(actor.kind == "member" for actor in features.superuser_actors())
    assert features.private_superuser_actors() == []


def test_qq_official_identity_keeps_openids_opaque() -> None:
    event = _sdk_event(
        event_type="GROUP_AT_MESSAGE_CREATE",
        chat_scope="group",
        chat_id="opaque-group",
        user_id="opaque-member",
        content="help",
        raw={
            "author": {
                "id": "native-author-id",
                "bot": False,
                "member_openid": "opaque-member",
                "member_role": "member",
            },
            "group_id": "native-group-id",
            "group_openid": "opaque-group",
            "msg_idx": "sequence-1",
            "mentions": [
                {
                    "scope": "single",
                    "bot": True,
                    "id": "bot-id",
                    "is_you": True,
                    "member_openid": "bot-openid",
                    "username": "babyQ",
                },
                {
                    "scope": "single",
                    "bot": False,
                    "id": "member-id",
                    "is_you": False,
                    "member_openid": "mentioned-openid",
                    "username": "target",
                },
            ],
        },
    )

    incoming = qq_official_incoming_message(event, account_id="example-app")

    assert incoming.platform is Platform.QQ_OFFICIAL
    assert incoming.actor == ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        "member",
        "opaque-group",
        account_id="example-app",
    )
    assert incoming.conversation == ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "opaque-group",
        account_id="example-app",
    )
    assert incoming.group_role == "member"
    assert incoming.direct_mentions == (
        ActorRef(
            Platform.QQ_OFFICIAL,
            "mentioned-openid",
            "member",
            "opaque-group",
            account_id="example-app",
        ),
    )
    assert incoming.sequence == "sequence-1"
    assert incoming.reply_deadline is not None
    assert incoming.reply_deadline.isoformat() == "2099-01-01T00:05:00+08:00"


def test_only_group_at_event_is_classified_as_bot_mention() -> None:
    full_message = _sdk_event(event_type="GROUP_MESSAGE_CREATE")
    at_message = _sdk_event(event_type="GROUP_AT_MESSAGE_CREATE")

    assert not qq_official_event_mentions_bot(full_message)
    assert qq_official_event_mentions_bot(at_message)


def test_qq_official_renderer_preserves_text_and_binary_image() -> None:
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "group", "opaque-group")
    rendered = render_qq_official_outbound_message(
        OutboundMessage(
            (
                TextPart("result"),
                BinaryImagePart(b"image", "image/png", "preview.png"),
            )
        ),
        conversation=conversation,
    )

    assert rendered[0] == QQOfficialTextPayload("result")
    assert rendered[1] == QQOfficialImagePayload(
        content=b"image",
        filename="preview.png",
    )


def test_qq_official_renderer_uses_current_member_mention_markup() -> None:
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "opaque-group",
        account_id="example-app",
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        'member-"openid',
        "member",
        conversation.id,
        account_id="example-app",
    )

    rendered = render_qq_official_outbound_message(
        OutboundMessage((MentionPart(member), TextPart(" result"))),
        conversation=conversation,
    )

    assert rendered == (
        QQOfficialTextPayload(
            '<qqbot-at-user id="member-&quot;openid" /> result'
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_qq_official_delivery_commits_only_after_transport_success(
    *,
    fail: bool,
) -> None:
    event = _sdk_event()
    incoming = qq_official_incoming_message(event, account_id="example-app")
    delivered: list[bool] = []
    reply = PortableReply(
        OutboundMessage.from_text("result"),
        on_delivered=lambda: delivered.append(True),
    )
    bot = _FakeOfficialBot(fail=fail)
    messenger = QQOfficialOutboundMessenger(
        {"example-app": False},
        bot_provider=lambda _app_id: bot,
    )
    await deliver_qq_official_reply(messenger, incoming, reply)

    assert bot.sent == 1
    assert delivered == ([] if fail else [True])
    assert bot.calls[0][3:] == ("message-id", 1)


@pytest.mark.asyncio
async def test_qq_official_delivery_sends_additional_messages_in_order() -> None:
    event = _sdk_event()
    incoming = qq_official_incoming_message(event, account_id="example-app")
    reply = PortableReply(
        OutboundMessage.from_text("first"),
        additional_messages=(
            OutboundMessage.from_text("second"),
            OutboundMessage.from_text("third"),
        ),
    )
    bot = _FakeOfficialBot()
    messenger = QQOfficialOutboundMessenger(
        {"example-app": False},
        bot_provider=lambda _app_id: bot,
    )

    await deliver_qq_official_reply(messenger, incoming, reply)

    expected_calls = [
        ("message-id", 1),
        ("message-id", 2),
        ("message-id", 3),
    ]
    assert bot.sent == len(expected_calls)
    assert [call[3:] for call in bot.calls] == expected_calls


@pytest.mark.asyncio
async def test_qq_official_delivery_sends_deferred_result_after_ack() -> None:
    event = _sdk_event(content="/刷新样本")
    incoming = qq_official_incoming_message(event, account_id="example-app")
    lifecycle: list[str] = []

    async def operation(progress: Callable[[str], Awaitable[None]]) -> str:
        lifecycle.append("prepared")
        await progress("started")
        lifecycle.append("executed")
        return "finished"

    reply = await progress_operation_reply(operation)
    bot = _FakeOfficialBot()
    messenger = QQOfficialOutboundMessenger(
        {"example-app": False},
        bot_provider=lambda _app_id: bot,
    )

    assert lifecycle == ["prepared"]
    await deliver_qq_official_reply(messenger, incoming, reply)

    assert lifecycle == ["prepared", "executed"]
    expected_calls = [
        ("message-id", 1),
        ("message-id", 2),
    ]
    assert bot.sent == len(expected_calls)
    assert [call[3:] for call in bot.calls] == expected_calls


@pytest.mark.asyncio
async def test_failed_initial_delivery_cancels_deferred_operation() -> None:
    event = _sdk_event(content="/刷新样本")
    incoming = qq_official_incoming_message(event, account_id="example-app")
    cancelled = asyncio.Event()

    async def operation(progress: Callable[[str], Awaitable[None]]) -> str:
        try:
            await progress("started")
            return "must not run"
        finally:
            cancelled.set()

    reply = await progress_operation_reply(operation)
    bot = _FakeOfficialBot(fail=True)
    messenger = QQOfficialOutboundMessenger(
        {"example-app": False},
        bot_provider=lambda _app_id: bot,
    )

    await deliver_qq_official_reply(messenger, incoming, reply)
    await asyncio.wait_for(cancelled.wait(), timeout=1)

    assert bot.sent == 1


@pytest.mark.asyncio
async def test_portable_router_reports_only_enabled_mvp_commands() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(
            features=["help", "about"],
            superusers=[],
        ),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-user",
        account_id="example-app",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id="example-app",
    )

    help_message = await router.dispatch(_portable_input("帮助", actor, conversation))
    assert help_message is not None
    assert isinstance(help_message.message.parts[0], TextPart)
    assert "关于" in help_message.message.parts[0].text
    assert "数据版本" not in help_message.message.parts[0].text
    assert (
        await router.dispatch(_portable_input("数据版本", actor, conversation))
        is None
    )


def test_portable_router_rejects_unimplemented_official_direct_command() -> None:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="missing",
                commands=(
                    CommandContract(
                        id="missing.command",
                        plugin_id="missing",
                        section="测试",
                        examples=("缺失命令",),
                        description="验证官方命令覆盖守护",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(PortableCommandRouterError, match=r"missing\.command"):
        PortableCommandRouter(
            catalog,
            {},
            build_onebot_feature_service(FeatureConfig(), ()),
            ai=cast("AiService", _FakeAi()),
            ai_input_routing=AiInputRoutingService(
                build_onebot_feature_service(FeatureConfig(), ()),
                catalog,
            ),
            addressed_input_hints=AddressedInputHintService(),
        )


@pytest.mark.asyncio
async def test_portable_router_runs_activity_queries_with_catalog_access() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(
            features=["seer_activity_query"],
            superusers=["opaque-admin"],
        ),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(activity=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
        activity=cast("ActivityService", _FakeActivityService()),
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        account_id="example-app",
    )
    member_conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        member.id,
        account_id="example-app",
    )

    ending = await router.dispatch(
        _portable_input("快结束活动", member, member_conversation)
    )
    newly_added = await router.dispatch(
        _portable_input("新增活动", member, member_conversation)
    )

    assert ending is not None
    assert cast("TextPart", ending.message.parts[0]).text == "快结束活动"
    assert newly_added is not None
    assert cast("TextPart", newly_added.message.parts[0]).text == "新增活动"
    assert not router.recognizes(
        _portable_input("/当前活动", member, member_conversation)
    )

    admin = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-admin",
        account_id="example-app",
    )
    admin_conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        admin.id,
        account_id="example-app",
    )
    current = await router.dispatch(
        _portable_input("/当前活动", admin, admin_conversation)
    )

    assert current is not None
    assert cast("TextPart", current.message.parts[0]).text == "当前活动"
    assert not router.recognizes(
        _portable_input("当前活动", admin, admin_conversation)
    )


@pytest.mark.asyncio
async def test_portable_router_enforces_operational_query_access() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(
            features=["server_status_query", "meeting"],
            superusers=["opaque-admin"],
        ),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(operations=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
        server_status=cast("ServerStatusService", _FakeServerStatusService()),
        meeting_number="6638682008",
        meeting_template="会议号：{meeting_number}",
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        account_id="example-app",
    )
    admin = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-admin",
        account_id="example-app",
    )

    async def dispatch(text: str, actor: ActorRef) -> str | None:
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            actor.id,
            account_id="example-app",
        )
        reply = await router.dispatch(_portable_input(text, actor, conversation))
        if reply is None:
            return None
        return cast("TextPart", reply.message.parts[0]).text

    assert await dispatch("开服了吗", member) == "normal status"
    assert await dispatch("会议", member) == "会议号：663-868-2008"
    assert await dispatch("/开服查询", member) is None
    assert await dispatch("/无头状态", member) is None
    assert await dispatch("/开服查询", admin) == "admin status"
    assert await dispatch("/无头状态", admin) == "instance status"


@pytest.mark.asyncio
async def test_portable_router_runs_superuser_maintenance_with_delivery_gates() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=[], superusers=["opaque-admin"]),
    )
    docker_update = _FakeDockerUpdateService()
    router = build_portable_command_router(
        catalog=_portable_catalog(maintenance=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
        data_sync=cast("DataSyncService", _FakeDataSyncService()),
        docker_update=cast("DockerUpdateService", docker_update),
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        account_id="example-app",
    )
    admin = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-admin",
        account_id="example-app",
    )

    def context(text: str, actor: ActorRef) -> MessageInputContext:
        return _portable_input(
            text,
            actor,
            ConversationRef(
                Platform.QQ_OFFICIAL,
                "private",
                actor.id,
                account_id="example-app",
            ),
        )

    assert await router.dispatch(context("/更新数据", member)) is None
    assert await router.dispatch(context("/检查更新镜像", member)) is None
    assert await router.dispatch(context("/重启机器人", member)) is None

    check = await router.dispatch(context("/更新数据", admin))
    assert check is not None
    assert cast("TextPart", check.message.parts[0]).text == "data check start"
    check.delivered()
    assert check.follow_up is not None
    menu = await check.follow_up()
    assert cast("TextPart", menu.parts[0]).text == "data menu"

    sync = await router.dispatch(context("1", admin))
    assert sync is not None
    assert cast("TextPart", sync.message.parts[0]).text == "data sync start"
    sync.delivered()
    assert sync.follow_up is not None
    result = await sync.follow_up()
    assert cast("TextPart", result.parts[0]).text == "data sync done"

    image = await router.dispatch(context("/检查更新镜像", admin))
    assert image is not None
    assert cast("TextPart", image.message.parts[0]).text == "image check start"
    image.delivered()
    assert image.follow_up is not None
    image_result = await image.follow_up()
    assert cast("TextPart", image_result.parts[0]).text == "image check done"

    maintenance = await router.dispatch(context("/重启机器人", admin))
    assert maintenance is not None
    assert "选择机器人维护操作" in cast(
        "TextPart", maintenance.message.parts[0]
    ).text
    prepared = await router.dispatch(context("1", admin))
    assert prepared is not None
    assert cast("TextPart", prepared.message.parts[0]).text == "maintenance prepared"
    assert docker_update.executed == []
    prepared.delivered()
    assert prepared.follow_up is not None
    restarted = await prepared.follow_up()
    assert cast("TextPart", restarted.parts[0]).text == "机器人维护操作已提交。"
    assert docker_update.executed == ["process"]


@pytest.mark.asyncio
async def test_portable_router_limits_rank_display_setting_to_group_managers() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["seer_rank"]),
    )
    rank_queries = _FakeRankQueries()
    router = build_portable_command_router(
        catalog=_portable_catalog(rank_display=True),
        about=AboutService("test"),
        seer=_fake_seer(rank_queries=rank_queries),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        account_id="example-app",
    )
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        conversation.id,
        account_id="example-app",
    )

    member_context = _portable_input(
        "/榜单显示 20",
        actor,
        conversation,
        group_role="member",
        mentions_bot=False,
    )
    manager_context = _portable_input(
        "/榜单显示 20",
        actor,
        conversation,
        group_role="admin",
        mentions_bot=False,
    )

    assert not router.recognizes(member_context)
    assert await router.dispatch(member_context) is None
    reply = await router.dispatch(manager_context)

    assert reply is not None
    assert cast("TextPart", reply.message.parts[0]).text == (
        "榜单显示:example-app:group-openid:member-openid:20"
    )


@pytest.mark.asyncio
async def test_portable_router_limits_bilibili_refresh_to_superusers() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(
            features=["bili_push"],
            superusers=["opaque-admin"],
        ),
    )
    refresh_calls = 0

    async def notify_auth_invalid(_reason: str) -> None:
        return None

    async def manual_refresh() -> str:
        nonlocal refresh_calls
        refresh_calls += 1
        return "✅ 动态刷新完成。"

    router = build_portable_command_router(
        catalog=_portable_catalog(bilibili=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
        bilibili=cast("BilibiliService", SimpleNamespace()),
        bilibili_monitor=cast(
            "BilibiliMonitorService",
            SimpleNamespace(
                notify_auth_invalid=notify_auth_invalid,
                manual_refresh=manual_refresh,
            ),
        ),
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        account_id="example-app",
    )
    admin = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-admin",
        account_id="example-app",
    )

    def private_context(actor: ActorRef) -> MessageInputContext:
        return _portable_input(
            "/动态刷新",
            actor,
            ConversationRef(
                Platform.QQ_OFFICIAL,
                "private",
                actor.id,
                account_id=actor.account_id,
            ),
        )

    assert not router.recognizes(private_context(member))
    assert await router.dispatch(private_context(member)) is None
    reply = await router.dispatch(private_context(admin))

    assert reply is not None
    assert cast("TextPart", reply.message.parts[0]).text == "✅ 动态刷新完成。"
    assert refresh_calls == 1


@pytest.mark.asyncio
async def test_portable_router_runs_pet_config_image_query() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["pet_config"]),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(pet_config=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
        pet_config=cast("PetConfigQueryService", _FakePetConfigService()),
    )
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-user",
        account_id="example-app",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id="example-app",
    )

    reply = await router.dispatch(_portable_input("雷伊配置", actor, conversation))

    assert reply is not None
    assert reply.message.parts == (
        BinaryImagePart(b"pet-config", "image/png"),
    )


@pytest.mark.asyncio
async def test_portable_router_restricts_rank_status_to_account_superuser() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(
            features=["seer_rank"],
            superusers=["opaque-admin"],
        ),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(rank_status=True),
        about=AboutService("test"),
        seer=_fake_seer(
            rank_admin=cast("RankAdminService", _FakeRankAdminService())
        ),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    member = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        account_id="example-app",
    )
    admin = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-admin",
        account_id="example-app",
    )

    async def dispatch(text: str, actor: ActorRef) -> str | None:
        conversation = ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            actor.id,
            account_id="example-app",
        )
        reply = await router.dispatch(_portable_input(text, actor, conversation))
        if reply is None:
            return None
        return cast("TextPart", reply.message.parts[0]).text

    assert await dispatch("/样本情况", member) is None
    assert await dispatch("/刷新样本", member) is None
    assert await dispatch("/榜单情况", member) is None
    assert await dispatch("/样本情况", admin) == "sample status"
    assert await dispatch("/榜单情况", admin) == "page overview"
    assert await dispatch("/榜单情况 图鉴榜", admin) == "page status:图鉴积分"

    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        admin.id,
        account_id="example-app",
    )
    refresh = await router.dispatch(
        _portable_input("/刷新样本", admin, conversation)
    )

    assert refresh is not None
    assert cast("TextPart", refresh.message.parts[0]).text == "sample refresh start"
    refresh.delivery_failed()
    await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_selection", [False, True])
async def test_portable_router_runs_scoped_query_selection(
    *,
    fail_selection: bool,
) -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["seer_pet"]),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(pet_query=_FakePetQuery(fail_selection=fail_selection)),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        "member",
        "group-a",
        "example-app",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-a",
        account_id="example-app",
    )

    choices = await router.dispatch(
        _portable_input("精灵雷伊", actor, conversation)
    )
    assert choices is not None
    assert "1. 雷伊" in cast("TextPart", choices.message.parts[0]).text
    prompt = choices.message.prompt
    assert prompt is not None
    action = prompt.action_data(prompt.choices[1])
    assert router.recognizes(_portable_input(action, actor, conversation))

    selected = await router.dispatch(_portable_input(action, actor, conversation))
    assert selected is not None
    selected_text = cast("TextPart", selected.message.parts[0]).text
    assert selected_text == (
        DATABASE_UNAVAILABLE_MESSAGE if fail_selection else "精灵:2394"
    )


@pytest.mark.asyncio
async def test_portable_router_runs_peak_query_without_adapter_logic() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["seer_peak"]),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(peak_query=_FakePeakQuery()),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-user", account_id="example-app")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id="example-app",
    )

    result = await router.dispatch(_portable_input("竞技池", actor, conversation))

    assert result is not None
    assert cast("TextPart", result.message.parts[0]).text == "竞技池"


@pytest.mark.asyncio
async def test_portable_router_runs_team_query_with_opaque_context() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["seer_team"]),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(team_query=_FakeTeamQuery()),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        "member",
        "group-a",
        "example-app",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-a",
        account_id="example-app",
    )

    result = await router.dispatch(
        _portable_input("战队123456 654321", actor, conversation)
    )

    assert result is not None
    assert cast("TextPart", result.message.parts[0]).text == "战队:123456,654321"


@pytest.mark.asyncio
async def test_portable_router_runs_rank_query() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["seer_rank"]),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(rank_queries=_FakeRankQueries()),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-user", account_id="example-app")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id="example-app",
    )

    result = await router.dispatch(_portable_input("成就榜", actor, conversation))

    assert result is not None
    assert cast("TextPart", result.message.parts[0]).text == "榜单:成就点数:1:10"


@pytest.mark.asyncio
async def test_portable_router_routes_unclaimed_private_text_to_ai() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["about", "ai_chat"]),
    )
    ai = _FakeAi()
    router = build_portable_command_router(
        catalog=_portable_catalog(ai_chat=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", ai),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-user", account_id="example-app")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id="example-app",
    )

    reply = await router.dispatch(_portable_input("你好", actor, conversation))

    assert reply is not None
    assert cast("TextPart", reply.message.parts[0]).text == "AI回复"
    assert ai.calls == [(actor, conversation, "你好")]

    about = await router.dispatch(_portable_input("关于", actor, conversation))
    assert about is not None
    assert "IronsBot" in cast("TextPart", about.message.parts[0]).text
    assert len(ai.calls) == 1


@pytest.mark.asyncio
async def test_portable_router_does_not_send_unavailable_command_to_ai() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["ai_chat"]),
    )
    ai = _FakeAi()
    router = build_portable_command_router(
        catalog=_portable_catalog(ai_chat=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", ai),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-user", account_id="example-app")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id="example-app",
    )

    assert await router.dispatch(_portable_input("关于", actor, conversation)) is None
    assert ai.calls == []


@pytest.mark.asyncio
async def test_portable_router_routes_group_mention_by_ai_availability() -> None:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        "member",
        "group-a",
        "example-app",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-a",
        account_id="example-app",
    )
    ai = _FakeAi()
    enabled_features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["ai_chat"]),
    )
    enabled = build_portable_command_router(
        catalog=_portable_catalog(ai_chat=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=enabled_features,
        ai=cast("AiService", ai),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )

    reply = await enabled.dispatch(_portable_input("在吗", actor, conversation))

    assert reply is not None
    assert cast("TextPart", reply.message.parts[0]).text == "AI回复"
    assert ai.calls == [(actor, conversation, "在吗")]
    assert not enabled.recognizes(
        _portable_input("不会处理", actor, conversation, mentions_bot=False)
    )

    disabled_features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["help"]),
    )
    addressed_input_hints = AddressedInputHintService(max_per_window=1)
    disabled = build_portable_command_router(
        catalog=_portable_catalog(ai_chat=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=disabled_features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=addressed_input_hints,
        team_resource=_unused_team_resource(),
    )

    guarded = await disabled.dispatch(
        _portable_input("不会处理", actor, conversation)
    )

    assert guarded is not None
    assert cast("TextPart", guarded.message.parts[0]).text == (
        DIRECT_COMMAND_HELP_HINT_TEXT
    )
    assert (
        await disabled.dispatch(_portable_input("还是不会处理", actor, conversation))
        is None
    )


@pytest.mark.asyncio
async def test_portable_router_prompts_for_empty_group_ai_mention() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(features=["ai_chat"]),
    )
    ai = _FakeAi()
    router = build_portable_command_router(
        catalog=_portable_catalog(ai_chat=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", ai),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        "member",
        "group-a",
        "example-app",
    )
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-a",
        account_id="example-app",
    )

    reply = await router.dispatch(_portable_input("", actor, conversation))

    assert reply is not None
    assert cast("TextPart", reply.message.parts[0]).text == (
        "你想聊什么？可以直接写问题。"
    )
    assert ai.calls == []


@pytest.mark.asyncio
async def test_portable_router_ignores_blacklisted_official_actor() -> None:
    actor = ActorRef(Platform.QQ_OFFICIAL, "blocked-user")
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id)
    features = FeatureService(
        group_features={},
        actor_features={actor: frozenset({"blacklist"})},
        superusers=frozenset(),
        platform_default_features={
            Platform.QQ_OFFICIAL: frozenset({"about", "ai_chat"})
        },
    )
    ai = _FakeAi()
    router = build_portable_command_router(
        catalog=_portable_catalog(ai_chat=True),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", ai),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )
    incoming = _portable_input("关于", actor, conversation)

    assert not router.recognizes(incoming)
    assert await router.dispatch(incoming) is None
    assert ai.calls == []


def test_c2c_identity_uses_user_openid() -> None:
    event = _sdk_event()

    incoming = qq_official_incoming_message(event, account_id="example-app")

    assert incoming.actor == ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-user",
        account_id="example-app",
    )
    assert incoming.conversation == ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "opaque-user",
        account_id="example-app",
    )
    assert incoming.group_role is None
    assert incoming.reply_deadline is not None
    assert incoming.reply_deadline.isoformat() == "2099-01-01T01:00:00+08:00"


def test_bootstrap_constructs_qq_official_sdk_runtime(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[bot]
environment = "test"
plugin_manifest = "core"

[bot.qq_official]
enabled = true

[bot.qq_official.accounts.example_bot]
enabled = true
app_id = "example-app"
custom_keyboards = true

[operations.data_sync]
on_startup = false
interval_enabled = false

[operations.startup_notice]
enabled = false

[operations.clock_check]
enabled = false

[operations.docker_update]
check_on_startup = false
""".strip(),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "APP_CONFIG_PATH": str(config_path),
            "QQ_OFFICIAL_SECRET_EXAMPLE_BOT": "example-secret",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from ironsbot.app.bootstrap import bootstrap; "
                "app = bootstrap(); "
                "assert set(app.driver._adapters) == {'OneBot V11'}; "
                "assert app.resources.qq_official.account_ids == ('example-app',); "
                "sender = app.resources.qq_official.sender('example-app'); "
                "assert sender is not None and sender.custom_keyboards; "
                "print('QQ_OFFICIAL_BOOTSTRAP_OK')"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "QQ_OFFICIAL_BOOTSTRAP_OK" in result.stdout


def test_qq_official_quoted_reply_is_not_dispatched() -> None:
    event = _sdk_event(
        message_type=MSG_TYPE_QUOTE,
        raw={"message_scene": {"ext": ["ref_msg_idx=quoted-sequence"]}},
    )
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=_qq_config(
            features=["help", "about"],
            superusers=[],
        ),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(),
        player_id_resolver=cast("PlayerIdResolver", _FakePlayerIdResolver()),
        identity_links=_identity_links(),
        features=features,
        ai=cast("AiService", _FakeAi()),
        addressed_input_hints=AddressedInputHintService(),
        team_resource=_unused_team_resource(),
    )

    assert not qq_official_event_is_supported(
        event,
        account_id="example-app",
        router=router,
    )
