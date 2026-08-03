from nonebot.adapters import Bot, Message, MessageTemplate
from nonebot.adapters.onebot.v11 import MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg
from nonebot.rule import Rule
from nonebot_plugin_saa import Image

from ironsbot.core.features import FeatureService
from ironsbot.core.messaging import FIXED_IMAGE_COMMANDS, PicConfig
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import explicit_command
from ironsbot.services.messaging.sendpic import (
    ImageIndexOutOfRangeError,
    InvalidImageArgumentError,
    SendpicService,
)

FIXED_IMAGE_MISSING_MESSAGE = "图片文件不存在，请检查机器人图片目录。"


def install_fixed_images(
    registry: MatcherRegistry,
    service: SendpicService,
    features: FeatureService,
) -> None:
    for command, filename in FIXED_IMAGE_COMMANDS.items():
        matcher = registry.on_fullmatch(
            command,
            policy=CommandPolicy.command(
                f"sendpic_fixed.{command}",
                help_ids=(f"sendpic.fixed.{command}",),
            ),
            rule=Rule(
                lambda event: event_is_feature_allowed(features, event, "image")
            )
            & explicit_command(),
            priority=registry.priority("sendpic"),
            block=True,
        )

        async def _handle(
            matcher: Matcher,
            event: MessageEvent,
            filename: str = filename,
        ) -> None:
            data = await service.fixed_image(filename)
            if data is None:
                await finish_event_reply(
                    matcher,
                    event,
                    FIXED_IMAGE_MISSING_MESSAGE,
                )
                return
            await finish_event_reply(
                matcher,
                event,
                MessageSegment.image(data),
            )

        matcher.append_handler(_handle)


def create_image_command(
    registry: MatcherRegistry,
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
        rule=Rule(
            lambda event: event_is_feature_allowed(features, event, "image")
        )
        & explicit_command(),
    )
    template = config.message_template

    async def _handler(
        m: Matcher,
        bot: Bot,
        arg: Message = CommandArg(),
    ) -> None:
        arg_str = arg.extract_plain_text()
        try:
            result = await service.fetch(config, arg_str)
        except InvalidImageArgumentError:
            raise FinishedException from None
        except ImageIndexOutOfRangeError as e:
            await m.finish(str(e))

        image = Image(result.data)
        await m.finish(
            MessageTemplate(template).format(
                command=config.command,
                random_text=result.random_text,
                index=result.index,
                total=result.total,
                image=await image.build(bot),
            )
        )

    matcher.append_handler(_handler)
    return matcher


def install(
    registry: MatcherRegistry,
    service: SendpicService,
    features: FeatureService,
) -> None:
    install_fixed_images(registry, service, features)
    for command in service.commands:
        create_image_command(registry, command, service, features)
