# SPDX-License-Identifier: MIT
"""Platform-neutral project information service and command contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import CommandContract
from ironsbot.core.outbound import OutboundMessage

if TYPE_CHECKING:
    from pathlib import Path

ABOUT_MESSAGE = """
🤖 IronsBot
版本：{version}
项目：https://github.com/Murmansk5000/IronsBot
上游作者：Nattsu39
上游项目：https://github.com/Nattsu39/IronsBot

这是一个可扩展的自定义赛尔号机器人，当前版本以自定义功能为主：
米米号与战队查询、B站动态、活动提醒、榜单、群星牌、
固定图片/文本回复、AI 聊天和 Unraid 友好部署。

鸣谢：
- Nattsu39：IronsBot 上游项目。
- 火火（GitHub：Yogurt114514）：西塔伦Bot 的作者与本项目早期来源。
- SeerAPI 开源团队：数据模型、构建工具与基础数据链路。
- HurryWang（GitHub：WhY15w）：Unity 配置解析与下周预告图提取工具。
- SeerRadar：Sequ 数据参考；oldml：saixiaoxi 无头登录参考。

完整项目与工具鸣谢：https://github.com/Murmansk5000/IronsBot#%E9%B8%A3%E8%B0%A2
""".strip()


@dataclass(frozen=True, slots=True)
class AboutService:
    version: str

    @classmethod
    def from_version_file(cls, path: Path) -> AboutService:
        try:
            version = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            version = "未知"
        return cls(version or "未知")

    def message(self) -> OutboundMessage:
        return OutboundMessage.from_text(ABOUT_MESSAGE.format(version=self.version))


def about_command_contracts() -> tuple[CommandContract, ...]:
    """Describe the direct project information command."""

    return (
        CommandContract(
            id="about",
            plugin_id="about",
            section="查看",
            examples=("关于",),
            description="查看项目、版本和主要能力",
            features_any=("about",),
        ),
    )
