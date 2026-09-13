from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.adapters.qq import MessageSegment
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    GroupAtMessageCreateEvent,
)

from ironsbot.config.loader import load_settings
from ironsbot.config.models.features import FeatureConfig, build_onebot_feature_service
from ironsbot.config.models.settings import QQOfficialConfig
from ironsbot.core.command_catalog import CommandCatalog
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.qq_official.identity import qq_official_incoming_message
from ironsbot.integrations.qq_official.message_rendering import (
    render_qq_official_outbound_message,
)
from ironsbot.integrations.qq_official.runtime import (
    qq_official_event_is_supported,
)
from ironsbot.services.about import AboutService, about_command_contracts
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.portable_commands import build_portable_command_router
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.query_result import QueryChoice, QueryReply, QueryResult

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.resources import SeerQueryResources


class _FakeDataQueries:
    async def data_version(self) -> str:
        return "version"

    async def season_countdown(self) -> str:
        return "season"

    async def weekly_preview(self) -> DataQueryImageReply:
        return DataQueryImageReply(b"preview")


class _FakePlayerIdResolver:
    def has_known_reference(self, _value: str) -> bool:
        return False


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


def _fake_seer(*, pet_query: object | None = None) -> SeerQueryResources:
    unused = _UnusedQueryService()
    return cast(
        "SeerQueryResources",
        SimpleNamespace(
            data_queries=_FakeDataQueries(),
            pet_query=pet_query or unused,
            mintmark=unused,
            equipment=unused,
            type_query=unused,
            battle_effect=unused,
        ),
    )


def _portable_catalog() -> CommandCatalog:
    command_ids = {
        "seer.data.query",
        "seer.pet.query",
        "seer.pet.image",
        "seer.mintmark.query",
        "seer.equipment.query",
        "seer.type.query",
    }
    seer_contracts = tuple(
        contract
        for contract in seer_command_contracts(
            cast("PlayerIdResolver", _FakePlayerIdResolver())
        )
        if contract.id in command_ids
    )
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(id="help", commands=help_command_contracts()),
            PluginContribution(id="about", commands=about_command_contracts()),
            PluginContribution(id="seer_query", commands=seer_contracts),
        ),
        known_features=(
            "help",
            "about",
            "seer_data",
            "seer_pet",
            "seer_mintmark",
            "seer_equipment",
            "seer_type",
        ),
    )
    return catalog


def test_qq_official_config_loads_credentials_from_environment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "ironsbot.toml"
    path.write_text(
        """
[bot.qq_official]
enabled = true
app_id = "example-app"
features = ["help", "about", "seer_data"]
superusers = ["opaque-admin"]
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(
        path,
        env={
            "QQ_OFFICIAL_TOKEN": "example-token",
            "QQ_OFFICIAL_SECRET": "example-secret",
        },
    )

    assert settings.bot.qq_official.enabled
    assert settings.bot.qq_official.token == "example-token"
    assert settings.bot.qq_official.secret == "example-secret"
    assert settings.bot.qq_official.superusers == ["opaque-admin"]


def test_qq_official_identity_keeps_openids_opaque() -> None:
    event = GroupAtMessageCreateEvent.model_validate(
        {
            "id": "message-id",
            "content": "help",
            "timestamp": "2026-09-13T00:00:00+08:00",
            "author": {
                "id": "native-author-id",
                "bot": False,
                "member_openid": "opaque-member",
                "member_role": "member",
            },
            "group_id": "native-group-id",
            "group_openid": "opaque-group",
            "msg_idx": "sequence-1",
            "to_me": True,
        }
    )

    incoming = qq_official_incoming_message(event)

    assert incoming.platform is Platform.QQ_OFFICIAL
    assert incoming.actor == ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-member",
        "member",
        "opaque-group",
    )
    assert incoming.conversation == ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "opaque-group",
    )
    assert incoming.sequence == "sequence-1"


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

    assert rendered[0] == MessageSegment.text("result")
    assert rendered[1].type == "file_image"
    assert rendered[1].data["file_name"] == "preview.png"


@pytest.mark.asyncio
async def test_portable_router_reports_only_enabled_mvp_commands() -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=QQOfficialConfig(
            features=["help", "about"],
            superusers=[],
        ),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(),
        features=features,
    )
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-user")
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id)

    help_message = await router.dispatch(
        "帮助",
        actor=actor,
        conversation=conversation,
    )
    assert help_message is not None
    assert isinstance(help_message.parts[0], TextPart)
    assert "关于" in help_message.parts[0].text
    assert "数据版本" not in help_message.parts[0].text
    assert (
        await router.dispatch(
            "数据版本",
            actor=actor,
            conversation=conversation,
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_selection", [False, True])
async def test_portable_router_runs_scoped_query_selection(
    *,
    fail_selection: bool,
) -> None:
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=QQOfficialConfig(features=["seer_pet"]),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(pet_query=_FakePetQuery(fail_selection=fail_selection)),
        features=features,
    )
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-member", "member", "group-a")
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "group", "group-a")

    choices = await router.dispatch(
        "精灵雷伊",
        actor=actor,
        conversation=conversation,
    )
    assert choices is not None
    assert "1. 雷伊" in cast("TextPart", choices.parts[0]).text
    assert router.recognizes("2", actor=actor, conversation=conversation)

    selected = await router.dispatch("2", actor=actor, conversation=conversation)
    assert selected is not None
    selected_text = cast("TextPart", selected.parts[0]).text
    assert selected_text == (
        DATABASE_UNAVAILABLE_MESSAGE if fail_selection else "精灵:2394"
    )


def test_c2c_identity_uses_user_openid() -> None:
    event = C2CMessageCreateEvent.model_validate(
        {
            "id": "message-id",
            "content": "about",
            "timestamp": "2026-09-13T00:00:00+08:00",
            "author": {
                "id": "native-author-id",
                "user_openid": "opaque-user",
            },
            "to_me": True,
        }
    )

    incoming = qq_official_incoming_message(event)

    assert incoming.actor == ActorRef(Platform.QQ_OFFICIAL, "opaque-user")
    assert incoming.conversation == ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "opaque-user",
    )


def test_bootstrap_registers_qq_official_adapter(tmp_path: Path) -> None:
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(
        """
[bot]
environment = "test"
plugin_manifest = "core"

[bot.qq_official]
enabled = true
app_id = "example-app"

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
            "QQ_OFFICIAL_TOKEN": "example-token",
            "QQ_OFFICIAL_SECRET": "example-secret",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from ironsbot.app.bootstrap import bootstrap; "
                "app = bootstrap(); "
                "assert {'OneBot V11', 'QQ'} <= set(app.driver._adapters); "
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
    event = C2CMessageCreateEvent.model_validate(
        {
            "id": "message-id",
            "content": "about",
            "timestamp": "2026-09-13T00:00:00+08:00",
            "author": {
                "id": "native-author-id",
                "user_openid": "opaque-user",
            },
            "reply": {
                "content": "quoted",
                "message_type": 0,
                "msg_idx": "quoted-sequence",
            },
            "to_me": True,
        }
    )
    features = build_onebot_feature_service(
        FeatureConfig(),
        (),
        qq_official=QQOfficialConfig(
            features=["help", "about"],
            superusers=[],
        ),
    )
    router = build_portable_command_router(
        catalog=_portable_catalog(),
        about=AboutService("test"),
        seer=_fake_seer(),
        features=features,
    )

    assert not qq_official_event_is_supported(event, router)
