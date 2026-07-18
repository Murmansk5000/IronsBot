from collections.abc import AsyncGenerator, Callable
from pathlib import Path

from nonebot.adapters import Bot, Message, MessageTemplate
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg, Depends
from nonebot.rule import Rule
from nonebot_plugin_saa import Image

from ironsbot.config.models.message import PicConfig, SendpicBehaviorConfig
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.utils.rule import no_reply

from .backend import ImageBackend
from .backends import CnbBackend, LocalBackend
from .image_selection_service import (
    ImageIndexOutOfRangeError,
    InvalidImageArgumentError,
    build_image_file_path,
    select_image,
)

CNB_CONFIG_REQUIRED_ERROR = "启用 CNB 图床时必须配置 token 和 cnb_repo"


def get_cnb_backend(
    token: str, repo: str
) -> Callable[[], AsyncGenerator[ImageBackend, None]]:
    async def _inner() -> AsyncGenerator[ImageBackend, None]:
        async with CnbBackend(token, repo=repo) as cnb:
            yield cnb

    return _inner


def get_local_backend(
    root_path: Path,
) -> Callable[[], AsyncGenerator[ImageBackend, None]]:
    async def _inner() -> AsyncGenerator[ImageBackend, None]:
        async with LocalBackend(root_path) as local:
            yield local

    return _inner


def create_image_command(
    registry: MatcherRegistry,
    config: PicConfig,
    backend_factory: Callable[..., AsyncGenerator[ImageBackend, None]],
) -> type[Matcher]:
    """根据配置创建一个「随机/指定索引 + 图床后端」的命令。"""
    matcher = registry.on_command(
        config.command,
        policy=CommandPolicy.command(f"sendpic.{config.id}"),
        aliases=set(config.aliases),
        rule=Rule(lambda event: is_event_feature_allowed(event, "image")) & no_reply(),
    )
    template = config.message_template

    async def _handler(
        m: Matcher,
        bot: Bot,
        arg: Message = CommandArg(),
        backend: ImageBackend = Depends(backend_factory),
    ) -> None:
        max_index = await backend.count(config.image_dir)
        arg_str = arg.extract_plain_text()
        try:
            selection = select_image(arg_str, max_index)
        except InvalidImageArgumentError:
            raise FinishedException from None
        except ImageIndexOutOfRangeError as e:
            await m.finish(str(e))

        file_path = build_image_file_path(
            config.image_dir,
            config.image_filename_template,
            selection.index,
        )
        image = Image(await backend.get_file(file_path))
        await m.finish(
            MessageTemplate(template).format(
                command=config.command,
                random_text=selection.random_text,
                index=selection.index,
                total=max_index,
                image=await image.build(bot),
            )
        )

    matcher.append_handler(_handler)
    return matcher


def install(
    registry: MatcherRegistry,
    config: SendpicBehaviorConfig,
    cnb_token: str | None,
) -> None:
    for command in config.configs:
        if command.id not in config.enabled_ids:
            continue
        if command.backend == "cnb":
            if not cnb_token or not config.cnb_repo:
                raise ValueError(CNB_CONFIG_REQUIRED_ERROR)
            backend_factory = get_cnb_backend(cnb_token, config.cnb_repo)
        elif command.backend == "local":
            backend_factory = get_local_backend(config.local_root)
        else:
            raise ValueError(f"不支持的图床类型：{command.backend}")

        create_image_command(registry, command, backend_factory)
