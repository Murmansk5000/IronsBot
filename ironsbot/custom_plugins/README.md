# 自定义插件目录

这个目录用于放置 IronsBot 的自定义插件。用户可触发的功能应优先放在
`ironsbot/custom_plugins`；`ironsbot/plugins` 只保留基础设施或上游/vendor 代码。

运行入口 `bot.py` 会按显式顺序加载外部插件、基础设施插件和自定义插件。
`pyproject.toml` 不再扫描整个自定义插件目录，避免空目录、试验代码或遗留插件被误加载：

```toml
plugin_dirs = []
```

新增可运行插件后，需要把模块名加入 `bot.py` 的 `CUSTOM_PLUGINS` 列表，避免
NoneBot 无序加载导致依赖插件先后顺序不稳定；没有加入 `bot.py` 的目录只会被视为普通代码。

## 当前插件

```text
ironsbot/custom_plugins/
  ai_chat/           # 接入 DeepSeek API，群聊 @机器人 或授权私聊触发
  bilibili_monitor/   # 监控指定 B 站账号动态，推送到配置的群/用户
  custom_about/       # 新版关于页
  custom_get_seer_info/ # 自定义赛尔号查询、榜单、群星牌、活动入口
  custom_help/        # 按当前群/私聊权限显示可用功能
  custom_sendpic/     # 本地固定关键词发图
  message_actions/    # 通用文本消息动作：指令回复、定时发送、批量推送、事件回复
  meeting_reply/      # 回复“开播/会议”的腾讯会议信息
  pet_config_reply/   # 对“精灵名 + 配置”提示暂不支持配置查询
  startup_notice/     # 机器人启动并连接后私聊通知超级管理员
  team_shortcut/      # 给战队群使用：群内短指令触发预设战队查询
```

## 新增插件

每个插件一个子目录，最小结构如下：

```text
ironsbot/custom_plugins/my_plugin/
  __init__.py
  config.py        # 可选：放配置模型
```

固定文本指令、定时私聊、定时群发优先不要写插件，直接用
`MODULES.message` 配置。确实需要业务逻辑时，插件只负责判断和生成文本，
最终发送走 `message_actions`。

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

模块配置统一写在 `ironsbot/shared/config/config.py`，插件自己的 `config.py`
只保留轻量代理或兼容导出，不再各自调用 `get_plugin_config`。

推荐写法：

```python
from ironsbot.shared.config.config import Config, get_shared_config

plugin_config = get_shared_config()
my_plugin_config = plugin_config.modules.my_plugin
```

新增模块配置时，先在 shared config 里加 Pydantic schema，再从插件侧代理引用。

然后在 `.env.dev`、`.env.prod`、Unraid 模板变量或 Docker 环境变量中只填
密钥、账号、群号、战队号和功能策略；确实要覆盖模块默认值时使用 `MODULES`
写局部覆盖。

示例：

```env
GROUP_ALIASES={"admin":686376929,"main":123456789}
FEATURE_GROUP_POLICY={"admin":["admin_notice"],"main":["seer","meeting","activity_query","bili_query","bili_push","team","ai_chat","ai_intent"]}
TEAM_IDS=[]
TEAM_RESOURCE_USERS=[]

AI_KEY=sk-...

MODULES={"bilibili":{"push":{"groups":{"main":{"uids":[1310714247,123456789],"mode":"full","uid_modes":{"123456789":"link"}}}}}}
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
