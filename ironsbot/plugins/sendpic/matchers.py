from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import cast

from nonebot import MatcherGroup, logger
from nonebot.adapters import Bot, Message, MessageTemplate
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg, Depends
from nonebot.rule import Rule
from nonebot_plugin_saa import Image

from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.messaging import register_command_matcher
from ironsbot.utils.rule import no_reply

from .backend import ImageBackend
from .backends import CnbBackend, LocalBackend
from .config import (
    PicConfig,
    enabled_pic_configs,
    get_sendpic_cnb_repo,
    get_sendpic_cnb_token,
    get_sendpic_config,
    get_sendpic_local_root,
    pic_id_is_enabled,
)
from .image_selection_service import (
    ImageIndexOutOfRangeError,
    InvalidImageArgumentError,
    build_image_file_path,
    select_image,
)

matcher_group = MatcherGroup()


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
    group: MatcherGroup,
    config: PicConfig,
    backend_factory: Callable[..., AsyncGenerator[ImageBackend, None]],
) -> type[Matcher] | None:
    """根据配置创建一个「随机/指定索引 + 图床后端」的命令。"""
    if not pic_id_is_enabled(get_sendpic_config(), config.id):
        logger.warning(
            f"图片类型【{config.id}】未启用，命令【{config.command}】将不会生效"
        )

    matcher = group.on_command(
        config.command,
        aliases=set(config.aliases),
        rule=Rule(lambda event: is_event_feature_allowed(event, "image")) & no_reply(),
    )
    register_command_matcher(matcher, f"sendpic.{config.id}")
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


for _cmd in enabled_pic_configs(get_sendpic_config()):
    if _cmd.backend == "cnb":
        backend_factory = get_cnb_backend(
            cast("str", get_sendpic_cnb_token()),
            cast("str", get_sendpic_cnb_repo()),
        )
    elif _cmd.backend == "local":
        backend_factory = get_local_backend(get_sendpic_local_root())
    else:
        raise ValueError(f"不支持的图床类型：{_cmd.backend}")

    create_image_command(matcher_group, _cmd, backend_factory)
