# 自定义插件目录

这个目录用于放置 fork 里的本地自定义插件。原项目插件保留在
`ironsbot/plugins`，自己的功能放在这里，方便后续同步上游时减少冲突。

项目已经在 `pyproject.toml` 中配置：

```toml
plugin_dirs = ["ironsbot/plugins", "ironsbot/custom_plugins"]
```

因此每个带有 `__init__.py` 的子目录都会被 NoneBot 自动加载。

## 当前插件

```text
ironsbot/custom_plugins/
  bilibili_monitor/   # 监控指定 B 站账号动态，推送到配置的群/用户
  event_link/         # 回复“签到/活动/链接”，并可定时推送活动链接
  meeting_reply/      # 回复“开播/会议”的腾讯会议信息
  pet_config_reply/   # 对“精灵名 + 配置”提示暂不支持配置查询
  scheduled_private_message/ # 定时向指定用户发送私聊消息
  sendpic_custom/     # 本地固定关键词发图
```

## 新增插件

每个插件一个子目录，最小结构如下：

```text
ironsbot/custom_plugins/my_plugin/
  __init__.py
  config.py        # 可选：放配置模型
```

最小命令示例：

```python
from nonebot.plugin import PluginMetadata, on_fullmatch

__plugin_meta__ = PluginMetadata(
    name="Ping",
    description="测试机器人是否在线",
    usage="ping",
)

ping = on_fullmatch("ping", priority=10, block=True)


@ping.handle()
async def handle_ping() -> None:
    await ping.finish("pong")
```

把代码放进某个插件目录的 `__init__.py`，重启机器人后即可测试。

## 配置原则

不要把 QQ 号、群号、账号、密码、Cookie、token 写死在代码里。公开仓库里只保留空
默认值或无敏感的示例值。

推荐写法：

```python
from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    my_plugin_groups: list[int] = Field(default_factory=list)


plugin_config = get_plugin_config(Config)
```

然后在 `.env.dev`、`.env.prod`、Unraid 模板变量或 Docker 环境变量中填实际值。

示例：

```env
MEETING_REPLY_NUMBER=1234567890
MEETING_REPLY_TEMPLATE="腾讯会议\n腾讯会议号：{meeting_number}\n点击链接直接加入：{meeting_url}"
MEETING_REPLY_GROUPS=[123456789,987654321]
MEETING_REPLY_USERS=[123456789]

EVENT_LINK_REPLY_GROUPS=[123456789]
EVENT_LINK_SEND_USERS=[123456789]
EVENT_LINK_SEND_HOUR=23

BILIBILI_MONITOR_UID=1310714247
BILIBILI_MONITOR_TARGET_GROUP_IDS=[123456789]
BILIBILI_MONITOR_TARGET_USER_IDS=[123456789]
BILIBILI_MONITOR_ADMIN_UIDS=[123456789]

SCHEDULED_PRIVATE_MESSAGES=[
  {
    "id": "morning",
    "user_ids": [123456789, 987654321],
    "hour": 8,
    "minute": 30,
    "message": "早上好"
  },
  {
    "id": "night",
    "user_ids": [123456789],
    "hour": 23,
    "minute": 0,
    "message": "该休息了"
  }
]
```

## 本地开发与部署

本地开发时使用 `.env.dev`，生产部署时使用 `.env.prod` 或 Unraid 模板变量。

常见流程：

```text
本地修改插件
  -> 测试
  -> commit
  -> push 到 GitHub main
  -> GitHub Actions 构建镜像
  -> Unraid 拉取新镜像并重启容器
```

如果只改群号、QQ 号、token 等运行配置，不需要重新构建镜像，直接改 `.env.prod`
或 Unraid 容器变量后重启容器即可。

## 隐私检查

提交前建议扫一遍敏感信息：

```powershell
rg "你的QQ号|群号|token|password|cookie" ironsbot/custom_plugins unraid .github
```

`.env.dev` 和 `.env.prod` 已被 `.gitignore` 忽略，不应提交到公开仓库。
