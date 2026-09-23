from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.consts import CMD_ARG_KEY, PREFIX_KEY
from nonebot.exception import FinishedException
from nonebot.rule import Rule, TrieRule, command, fullmatch

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.messaging import (
    PicConfig,
    SendpicBehaviorConfig,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.sendpic import LocalBackend
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.sendpic import (
    IndexedImageRequest,
    SendpicService,
    sendpic_command_contracts,
)

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot
from tests.helpers.onebot_events import group_message_event, private_message_event

ACTOR = ActorRef(Platform.ONEBOT, "100")
PRIVATE = ConversationRef(Platform.ONEBOT, "private", "100")
GROUP = ConversationRef(Platform.ONEBOT, "group", "200")
SELECTED_INDEX = 2
OUT_OF_RANGE_INDEX = 99
FEATURES = FeatureService(
    {GROUP: frozenset({"image", "ai_chat"})},
    {ACTOR: frozenset({"image", "ai_chat"})},
    frozenset(),
)


def _gallery(id_: str, name: str, aliases: set[str] | None = None) -> PicConfig:
    return PicConfig(
        id=id_,
        backend="local",
        command=name,
        aliases=aliases or set(),
        mode="indexed",
        image_dir=id_,
        image_filename_template="{index}.png",
    )


def _single(id_: str, name: str, aliases: set[str] | None = None) -> PicConfig:
    return PicConfig(
        id=id_,
        backend="local",
        command=name,
        aliases=aliases or set(),
        mode="single",
        image_file=f"{id_}.png",
    )


def _service(starts: tuple[str, ...] = ("/", "")) -> tuple[SendpicService, Mock]:
    backend = Mock(
        count=AsyncMock(return_value=3), get_file=AsyncMock(return_value=b"png")
    )
    return SendpicService(
        SendpicBehaviorConfig(
            configs=[
                _single("study-table", "学习力", {"学习力表", "学习力表格"}),
                _gallery("memes", "表情", {"表情包", "Gallery"}),
                _gallery("long", "表情包1"),
            ]
        ),
        lambda _kind: backend,
        command_starts=starts,
    ), backend


def _catalog(service: SendpicService) -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="sendpic", commands=sendpic_command_contracts(service)
            ),
        ),
        known_features={"image"},
    )
    return catalog


def _installed(
    service: SendpicService,
    monkeypatch: pytest.MonkeyPatch,
    features: FeatureService = FEATURES,
) -> tuple[dict[str, Rule], dict[str, Any]]:
    try:
        driver = nonebot.get_driver()
    except ValueError:
        nonebot.init()
        driver = nonebot.get_driver()
    monkeypatch.setattr(driver.config, "command_start", set(service.command_starts))
    monkeypatch.setattr(TrieRule, "prefix", type(TrieRule.prefix)())
    from ironsbot.plugins.onebot.sendpic import matchers

    rules: dict[str, Rule] = {}
    handlers: dict[str, Any] = {}

    def register(names: str | tuple[str, ...], **options: Any) -> Mock:
        matcher = Mock()
        (id_,) = options["policy"].help_ids
        if isinstance(names, str):
            grammar = command(names, *options["aliases"])
        else:
            grammar = fullmatch(names)
        rules[id_] = grammar & options["rule"]
        matcher.append_handler.side_effect = lambda handler: handlers.__setitem__(
            id_, handler
        )
        return matcher

    registry = Mock(
        on_command=Mock(side_effect=register), on_fullmatch=Mock(side_effect=register)
    )
    matchers.install(registry, service, features)
    return rules, handlers


@pytest.mark.parametrize("starts", [("/", ""), ("!",), ("/", "//")])
@pytest.mark.parametrize("private", [True, False])
@pytest.mark.asyncio
async def test_indexed_inputs_match_installed_rules_and_catalog(
    starts: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    *,
    private: bool,
) -> None:
    service, backend = _service(starts)
    catalog = _catalog(service)
    rules, _ = _installed(service, monkeypatch)
    context = CommandContext(ACTOR, PRIVATE if private else GROUP)
    prefix = "" if "" in starts else starts[0]
    for text, owner, index in (
        (prefix + "表情", "memes", None),
        (prefix + "表情包2", "memes", 2),
        ("  " + prefix + "Gallery\t２", "memes", 2),
        (prefix + "表情包1", "long", None),
        (prefix + "表情包12", "long", 2),
        (prefix + "表情0", "memes", 0),
        (prefix + "表情99", "memes", 99),
    ):
        event = (
            private_message_event(text, user_id=100)
            if private
            else group_message_event(text, user_id=100, group_id=200)
        )
        matched = []
        for id_, rule in rules.items():
            state: dict[str, Any] = {}
            TrieRule.get_value(cast("Bot", None), event, state)
            if await rule(cast("Bot", None), event, state):
                matched.append(id_)
                assert state["_indexed_image_request"] == IndexedImageRequest(
                    owner, index
                )
                original_arg = state[PREFIX_KEY][CMD_ARG_KEY].extract_plain_text()
                assert (int(original_arg) if original_arg else None) == index
        assert matched == [f"sendpic.{owner}"]
        assert [
            c.id
            for c in catalog.available_for_context(context, FEATURES)
            if c.matches_direct_input(context, text)
        ] == matched
        if private:
            assert not _capture_ai_prompt(
                event,
                {},
                AiInputRoutingService(FEATURES, catalog),
            )
    backend.count.assert_not_awaited()
    backend.get_file.assert_not_awaited()


@pytest.mark.parametrize(
    "text",
    [
        "表情abc",
        "表情包1x",
        "表情-1",
        "表情2 ",
        "表情²",
        "表情①",
        "GalleryX",
        "gallery2",
        "//表情2",
        "表 情2",
        "看看表情2",
        pytest.param("表情" + "9" * 5000, id="oversized-integer"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_image_arguments_are_not_claimed_or_loaded(
    text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, backend = _service()
    rules, _ = _installed(service, monkeypatch)
    event = private_message_event(text, user_id=100)
    for rule in rules.values():
        state = {}
        TrieRule.get_value(cast("Bot", None), event, state)
        assert not await rule(cast("Bot", None), event, state)
    assert not _catalog(service).claims_direct_input(
        CommandContext(ACTOR, PRIVATE), FEATURES, text
    )
    backend.count.assert_not_awaited()
    backend.get_file.assert_not_awaited()


def test_prefix_only_help_and_disabled_prefixes() -> None:
    service, _ = _service(("!",))
    commands = sendpic_command_contracts(service)
    indexed = next(c for c in commands if c.id == "sendpic.memes")
    assert indexed.examples == ("!表情", "!Gallery", "!表情包")
    assert indexed.matches_direct_input(CommandContext(ACTOR, PRIVATE), "!表情2")
    assert not indexed.matches_direct_input(CommandContext(ACTOR, PRIVATE), "表情2")
    assert "表情" not in service.exact_command_texts
    assert "!表情" in service.exact_command_texts
    disabled, _ = _service(())
    assert not any(c.mode == "indexed" for c in disabled.commands)
    assert all(
        c.id not in {"sendpic.memes", "sendpic.long"}
        for c in sendpic_command_contracts(disabled)
    )
    assert any(
        c.id == "sendpic.study-table" for c in sendpic_command_contracts(disabled)
    )


@pytest.mark.asyncio
async def test_single_images_keep_exact_fullmatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _service(("!",))
    rules, _ = _installed(service, monkeypatch)
    catalog = _catalog(service)
    for text, expected in (
        ("学习力", True),
        ("学习力表", True),
        ("!学习力", False),
        ("学 习力", False),
        (" 学习力", False),
        ("学习力2", False),
    ):
        event = private_message_event(text, user_id=100)
        assert (
            await rules["sendpic.study-table"](cast("Bot", None), event, {}) is expected
        )
        assert (
            catalog.claims_direct_input(CommandContext(ACTOR, PRIVATE), FEATURES, text)
            is expected
        )


def test_without_image_feature_known_image_command_does_not_fall_into_ai() -> None:
    service, _ = _service()
    disabled = FeatureService({}, {ACTOR: frozenset({"ai_chat"})}, frozenset())
    catalog = _catalog(service)
    assert not catalog.claims_direct_input(
        CommandContext(ACTOR, PRIVATE), disabled, "表情2"
    )
    assert catalog.recognizes_direct_input(CommandContext(ACTOR, PRIVATE), "表情2")
    assert not _capture_ai_prompt(
        private_message_event("表情2", user_id=100),
        {},
        AiInputRoutingService(disabled, catalog),
    )


@pytest.mark.asyncio
async def test_disabled_image_feature_rejects_installed_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, backend = _service()
    disabled = FeatureService({}, {ACTOR: frozenset({"ai_chat"})}, frozenset())
    rules, _ = _installed(service, monkeypatch, disabled)
    for text in ("表情2", "学习力"):
        event = private_message_event(text, user_id=100)
        for rule in rules.values():
            state = {}
            TrieRule.get_value(cast("Bot", None), event, state)
            assert not await rule(cast("Bot", None), event, state)
    backend.count.assert_not_awaited()


def test_disabled_gallery_is_absent_from_runtime_and_help() -> None:
    gallery = _gallery("disabled", "测试图")
    gallery.enabled = False
    provider = Mock()
    service = SendpicService(
        SendpicBehaviorConfig(configs=[gallery]),
        provider,
        command_starts=("",),
    )
    assert service.commands == ()
    assert sendpic_command_contracts(service) == ()
    assert service.parse_indexed("测试图2") is None
    provider.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [None, SELECTED_INDEX, OUT_OF_RANGE_INDEX])
async def test_handler_uses_parsed_index_once(
    index: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, backend = _service()
    rules, handlers = _installed(service, monkeypatch)
    event = private_message_event(
        "表情" + (str(index) if index is not None else ""), user_id=100
    )
    state = {}
    TrieRule.get_value(cast("Bot", None), event, state)
    assert await rules["sendpic.memes"](cast("Bot", None), event, state)
    parser = Mock(side_effect=AssertionError("handler must not parse again"))
    monkeypatch.setattr(service, "parse_indexed", parser)
    matcher = Mock(finish=AsyncMock(side_effect=FinishedException))
    with pytest.raises(FinishedException):
        await handlers["sendpic.memes"](matcher, state, event)
    parser.assert_not_called()
    backend.count.assert_awaited_once_with("memes")
    if index == OUT_OF_RANGE_INDEX:
        backend.get_file.assert_not_awaited()
        assert "1到3" in str(matcher.finish.call_args.args[0])
    else:
        backend.get_file.assert_awaited_once()
        path = backend.get_file.call_args.args[0]
        assert (
            path == "memes/2.png"
            if index == SELECTED_INDEX
            else path in {"memes/1.png", "memes/2.png", "memes/3.png"}
        )
        message = matcher.finish.await_args.args[0]
        assert message["image"]


def test_numbered_gallery_is_owned_by_its_contract() -> None:
    gallery = PicConfig(
        id="example-gallery",
        backend="local",
        command="表情",
        aliases={"表情包"},
        mode="indexed",
        image_dir="memes",
        image_filename_template="{index}.png",
    )
    service = SendpicService(
        SendpicBehaviorConfig(configs=[gallery]),
        lambda _kind: LocalBackend(Path()),
        command_starts=("/", ""),
    )
    context = CommandContext(
        ActorRef(Platform.ONEBOT, "100"),
        ConversationRef(Platform.ONEBOT, "private", "100"),
    )
    assert [
        c.id
        for c in sendpic_command_contracts(service)
        if c.matches_direct_input(context, "表情包2")
    ] == ["sendpic.example-gallery"]
