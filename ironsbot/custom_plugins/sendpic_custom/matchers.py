import random
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from typing import NoReturn, cast

from nonebot import MatcherGroup, logger
from nonebot.adapters import Bot, Message, MessageTemplate
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.params import CommandArg, Depends
from nonebot_plugin_saa import Image

from ironsbot.utils.rule import no_reply

from .backend import ImageBackend
from .backends import CnbBackend, LocalBackend
from .config import PicConfig, filter_enabled_configs, pic_id_is_enabled, plugin_config

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
    if not pic_id_is_enabled(config.id):
        logger.warning(
            f"图片类型【{config.id}】未启用，命令【{config.command}】将不会生效"
        )

    matcher = group.on_command(
        config.command, aliases=set(config.aliases), rule=no_reply()
    )
    template = config.message_template

    async def _handler(
        m: Matcher,
        bot: Bot,
        arg: Message = CommandArg(),
        backend: ImageBackend = Depends(backend_factory),
    ) -> NoReturn:
        max_index = await backend.count(config.image_dir)
        is_random = False
        arg_str = arg.extract_plain_text()
        if arg_str.isdigit():
            index = int(arg_str)
        elif not arg_str:
            index = random.randint(1, max_index)
            is_random = True
        else:
            raise FinishedException

        if not 1 <= index <= max_index:
            await m.finish(f"编号必须在1到{max_index}之间！")
        file_path = "/".join(
            [config.image_dir, config.image_filename_template.format(index=index)]
        )
        image = Image(await backend.get_file(file_path))
        await m.finish(
            MessageTemplate(template).format(
                command=config.command,
                random_text="随机" if is_random else "自选",
                index=index,
                total=max_index,
                image=await image.build(bot),
            )
        )

    matcher.append_handler(_handler)
    return matcher


for _cmd in filter_enabled_configs():
    if _cmd.backend == "cnb":
        backend_factory = get_cnb_backend(
            cast("str", plugin_config.sendpic_cnb_token),
            cast("str", plugin_config.sendpic_cnb_repo),
        )
    elif _cmd.backend == "local":
        backend_factory = get_local_backend(plugin_config.sendpic_local_root)
    else:
        raise ValueError(f"不支持的图床类型：{_cmd.backend}")

    create_image_command(matcher_group, _cmd, backend_factory)
