from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.messaging import PicConfig, SendpicBehaviorConfig
from ironsbot.core.outbound import BinaryImagePart, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.sendpic import LocalBackend
from ironsbot.services.ai.command_contracts import ai_chat_command_contracts
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.sendpic import (
    IndexedImageRequest,
    SendpicService,
    sendpic_command_contracts,
)
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_messaging_commands import (
    build_portable_sendpic_operations,
)
from ironsbot.services.portable_reply import deliver_portable_reply

ACTOR = ActorRef(Platform.ONEBOT, "100")
PRIVATE = ConversationRef(Platform.ONEBOT, "private", "100")
SELECTED_INDEX = 2
OUT_OF_RANGE_INDEX = 99


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


def _catalog(service: SendpicService, *, include_ai: bool = False) -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="sendpic", commands=sendpic_command_contracts(service)
            ),
            PluginContribution(
                id="ai_chat",
                commands=ai_chat_command_contracts(enabled=True) if include_ai else (),
            ),
        ),
        known_features={"image", "ai_chat"},
    )
    return catalog


def _context(
    text: str, platform: Platform, *, private: bool = True
) -> MessageInputContext:
    actor = ActorRef(platform, "100")
    conversation = ConversationRef(
        platform, "private" if private else "group", "100" if private else "200"
    )
    return MessageInputContext(
        IncomingMessageRef(platform, actor, conversation, "1", text), mentions_bot=False
    )


def _router(
    service: SendpicService,
    context: MessageInputContext,
    *,
    enabled: bool = True,
    include_ai: bool = False,
) -> PortableCommandRouter:
    allowed = frozenset({"image"} if enabled else {"ai_chat"})
    features = FeatureService(
        {context.message.conversation: allowed},
        {context.message.actor: allowed},
        frozenset(),
    )
    catalog = _catalog(service, include_ai=include_ai)
    return PortableCommandRouter(
        catalog,
        build_portable_sendpic_operations(service),
        features,
        ai=Mock(chat_reply=AsyncMock(return_value="AI")),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
    )


@pytest.mark.parametrize("starts", [("/", ""), ("!",), ("/", "//")])
@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("platform", list(Platform))
def test_indexed_inputs_share_public_catalog_grammar(
    starts: tuple[str, ...],
    platform: Platform,
    *,
    private: bool,
) -> None:
    service, backend = _service(starts)
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
        context = _context(text, platform, private=private)
        catalog_context = CommandContext(
            context.message.actor, context.message.conversation
        )
        assert service.parse_indexed(text) == IndexedImageRequest(owner, index)
        assert [
            contract.id
            for contract in sendpic_command_contracts(service)
            if contract.matches_direct_input(catalog_context, text)
        ] == [f"sendpic.{owner}"]
        assert _router(service, context).recognizes(context)
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
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.asyncio
async def test_invalid_image_arguments_are_not_claimed_or_loaded(
    text: str,
    platform: Platform,
) -> None:
    service, backend = _service()
    context = _context(text, platform)
    router = _router(service, context)
    assert not router.recognizes(context)
    assert await router.dispatch(context) is None
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


@pytest.mark.parametrize("platform", list(Platform))
def test_single_images_keep_exact_fullmatch(platform: Platform) -> None:
    service, backend = _service(("!",))
    for text, expected in (
        ("学习力", True),
        ("学习力表", True),
        ("!学习力", False),
        ("学 习力", False),
        (" 学习力", False),
        ("学习力2", False),
    ):
        context = _context(text, platform)
        assert _router(service, context).recognizes(context) is expected
    backend.count.assert_not_awaited()
    backend.get_file.assert_not_awaited()


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.asyncio
async def test_disabled_images_do_not_load_or_fall_into_ai(platform: Platform) -> None:
    service, backend = _service()
    for text in ("表情2", "学习力"):
        context = _context(text, platform)
        router = _router(service, context, enabled=False, include_ai=True)
        assert not router.recognizes(context)
        assert await router.dispatch(context) is None
    backend.count.assert_not_awaited()
    backend.get_file.assert_not_awaited()


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
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("index", [None, SELECTED_INDEX, OUT_OF_RANGE_INDEX])
async def test_public_execution_fetches_selected_image_once(
    index: int | None,
    platform: Platform,
) -> None:
    service, backend = _service()
    context = _context("表情" + (str(index) if index is not None else ""), platform)
    router = _router(service, context)
    assert router.recognizes(context)
    reply = await router.dispatch(context)
    assert reply is not None
    send = AsyncMock(return_value=SendResult(delivered=True, message_id="receipt"))
    await deliver_portable_reply(reply, send)
    backend.count.assert_awaited_once_with("memes")
    if index == OUT_OF_RANGE_INDEX:
        backend.get_file.assert_not_awaited()
        assert "1到3" in "".join(
            part.text for part in reply.message.parts if isinstance(part, TextPart)
        )
    else:
        backend.get_file.assert_awaited_once()
        path = backend.get_file.call_args.args[0]
        assert (
            path == "memes/2.png"
            if index == SELECTED_INDEX
            else path in {"memes/1.png", "memes/2.png", "memes/3.png"}
        )
        assert any(isinstance(part, BinaryImagePart) for part in reply.message.parts)


def test_numbered_gallery_is_owned_by_its_contract() -> None:
    gallery = _gallery("example-gallery", "表情", {"表情包"})
    service = SendpicService(
        SendpicBehaviorConfig(configs=[gallery]),
        lambda _kind: LocalBackend(Path()),
        command_starts=("/", ""),
    )
    context = CommandContext(ACTOR, PRIVATE)
    assert [
        c.id
        for c in sendpic_command_contracts(service)
        if c.matches_direct_input(context, "表情包2")
    ] == ["sendpic.example-gallery"]
