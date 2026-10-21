from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.messaging import PicConfig
from ironsbot.integrations.onebot.feature_policy import event_is_feature_allowed
from ironsbot.integrations.onebot.matcher_support import bind
from ironsbot.integrations.onebot.matchers import CommandPolicy, MatcherFactory
from ironsbot.integrations.onebot.portable_queries import (
    make_portable_operation_handler,
)
from ironsbot.integrations.onebot.rules import explicit_command
from ironsbot.services.messaging.sendpic import (
    SendpicService,
)
from ironsbot.services.portable_messaging_commands import (
    build_portable_sendpic_operations,
)

IMAGE_MISSING_MESSAGE = "图片文件不存在，请检查机器人图片目录。"
INDEXED_IMAGE_REQUEST_KEY = "_indexed_image_request"


def _match_indexed(
    service: SendpicService,
    command_id: str,
    event: MessageEvent,
    state: T_State,
) -> bool:
    parsed = service.parse_indexed(event.get_plaintext())
    if parsed is None or parsed.command_id != command_id:
        return False
    state[INDEXED_IMAGE_REQUEST_KEY] = parsed
    return True


def create_single_image_command(
    registry: MatcherFactory,
    config: PicConfig,
    service: SendpicService,
    features: FeatureService,
) -> None:
    matcher = registry.on_fullmatch(
        (config.command, *config.aliases),
        policy=CommandPolicy.command(
            f"sendpic.{config.id}",
            help_ids=(f"sendpic.{config.id}",),
        ),
        rule=Rule(lambda event: event_is_feature_allowed(features, event, "image"))
        & explicit_command(),
        priority=registry.priority("sendpic"),
        block=True,
    )

    matcher.append_handler(
        make_portable_operation_handler(
            build_portable_sendpic_operations(service)[f"sendpic.{config.id}"]
        )
    )


def create_image_command(
    registry: MatcherFactory,
    config: PicConfig,
    service: SendpicService,
    features: FeatureService,
) -> type[Matcher]:
    """根据配置创建一个「随机/指定索引 + 图床后端」的命令。"""
    matcher = registry.on_command(
        config.command,
        policy=CommandPolicy.command(
            f"sendpic.{config.id}",
            help_ids=(f"sendpic.{config.id}",),
        ),
        aliases=set(config.aliases),
        rule=Rule(lambda event: event_is_feature_allowed(features, event, "image"))
        & Rule(bind(_match_indexed, service, config.id))
        & explicit_command(),
    )
    matcher.append_handler(
        make_portable_operation_handler(
            build_portable_sendpic_operations(service)[f"sendpic.{config.id}"]
        )
    )
    return matcher


def install(
    registry: MatcherFactory,
    service: SendpicService,
    features: FeatureService,
) -> None:
    for command in service.commands:
        if command.mode == "single":
            create_single_image_command(registry, command, service, features)
        else:
            create_image_command(registry, command, service, features)
