# 插件适配层目录

这个目录目前承载 IronsBot 的 NoneBot 插件适配层：matcher、命令入口、生命周期注册
和少量插件本地配置访问函数。可复用的业务逻辑应优先放在 `ironsbot/services` 或
`ironsbot/shared`，插件目录只负责把 NoneBot 事件接到服务层。

`ironsbot/plugins` 只保留基础设施插件、协议/数据接入和必须随仓库保留的上游资产。
Seer 的 upstream Python 代码已经迁出；`custom_get_seer_info/_upstream` 现在只保留
模板和图片资产。

运行入口 `bot.py` 委托 `ironsbot/app/bootstrap.py`，并按
`ironsbot/app/plugin_manifest.py` 中的显式顺序加载外部插件、基础设施插件和自定义插件。
`pyproject.toml` 不再扫描整个自定义插件目录，避免空目录、试验代码或遗留插件被误加载：

```toml
plugin_dirs = []
```

新增可运行插件后，需要把模块名加入 `ironsbot/app/plugin_manifest.py`，
避免 NoneBot 无序加载导致依赖插件先后顺序不稳定；没有加入显式加载列表的目录只会被视为普通代码。

## 当前插件适配层

```text
ironsbot/custom_plugins/
  custom_get_seer_info/    # Seer 查询、榜单、群星牌、upstream helper 适配层
  message_actions/         # 通用消息动作适配层
  superuser_priority/      # 超级用户优先级控制
```

## 新增插件

每个插件一个子目录，最小结构如下：

```text
ironsbot/custom_plugins/my_plugin/
  __init__.py
  config.py        # 可选：放配置模型
```

固定文本指令、定时私聊、定时群发优先不要写新插件，直接用
`APP_CONFIG` 的 `[message]` 配置。确实需要业务逻辑时，插件只负责判断和生成文本，
最终发送走 `shared.messaging` 或现有 `message_actions` 适配层。

最小业务命令示例：

```python
from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.custom_plugins.message_actions import (
    command_text_matches,
    finish_event_reply,
)
from ironsbot.utils.rule import no_reply


async def _is_ping(event: MessageEvent) -> bool:
    return command_text_matches(event.get_plaintext(), ("ping",))


ping = on_message(rule=Rule(_is_ping) & no_reply(), priority=10, block=True)


@ping.handle()
async def handle_ping(matcher: Matcher, event: MessageEvent) -> None:
    await finish_event_reply(matcher, event, "pong")
```

把代码放进某个插件目录的 `__init__.py`，重启机器人后即可测试。

## 配置原则

不要把 QQ 号、群号、账号、密码、Cookie、token 写死在代码里。公开仓库里只保留空
默认值或无敏感的示例值。

行为配置统一写在 `ironsbot/config/models/` 的 APP_CONFIG schema 里，并由
`APP_CONFIG_PATH` 指向的 TOML 文件提供。插件自己的 `config.py` 只保留轻量访问函数，
不再各自调用 NoneBot 的 `get_plugin_config`，也不要新增旧的大 JSON 兼容入口。

推荐写法：

```python
from ironsbot.config.loader import get_app_config

def get_my_plugin_config():
    return get_app_config().message
```

新增模块配置时，先在 `ironsbot/config/models/` 里加 Pydantic schema 和默认值，
再从插件侧通过访问函数引用。导入插件时只允许创建 metadata 和薄 matcher；数据库打开、
目录创建、目标解析、网络请求、scheduler 注册和长任务都放到显式生命周期函数里。

`.env.dev`、`.env.prod`、Unraid 模板变量或 Docker 环境变量只保留密钥、账号凭据和部署运行参数。
群号、战队号、功能策略、B站订阅、消息动作等行为配置写入 TOML。

环境变量示例：

```env
APP_CONFIG_PATH=/config/ironsbot.toml
ONEBOT_ACCESS_TOKEN=change-me
SUPERUSERS=["123456789"]
AI_KEY=sk-...
HEADLESS_SEER_USER_ID=12345678
HEADLESS_SEER_PASSWORD=...
```

TOML 示例：

```toml
[feature]
group_aliases = { admin = 686376929, main = 123456789 }
group_policy = { admin = ["admin_notice"], main = ["seer", "meeting", "activity_query", "bili_query", "bili_push", "team", "ai_chat", "ai_intent"] }

[seer.team_shortcut]
team_ids = [1234567]
resource_users = [123456789]

[bilibili.push]
groups = { main = { uids = [1310714247, 123456789], mode = "full", uid_modes = { "123456789" = "link" } } }
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
