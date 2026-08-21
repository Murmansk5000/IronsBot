# 消息推送中心（push）

通用消息推送插件：为 irons-bot 提供**主动消息推送基础设施**。

- **主题（Topic）注册**：其他插件可注册推送主题，用户订阅后接收推送
- **订阅管理命令**：普通用户可自助订阅/退订；超级用户可创建/删除/启停主题并全局推送
- **定时 + 编程推送**：支持 APScheduler 定时推送（内容提供器模式）与代码主动调用
- **状态持久化**：订阅关系与推送历史使用 SQLModel + 本地 SQLite 持久化，机器人重启不丢失

## 配置

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `PUSH_DATA_DIR` | localstore `push` 数据目录 | SQLite 数据文件所在目录 |
| `PUSH_MAX_HISTORY` | `500` | 每个主题保留的最大推送历史条数 |
| `PUSH_DEDUP_WINDOW_SECONDS` | `3600` | 去重窗口（秒），窗口内同 `dedup_key` 的成功推送会被跳过 |
| `PUSH_ADMIN_MANAGE_GROUP_IDS` | `[]` | 可选：推送管理命令可用的群号白名单，空表示不限制 |

## 命令

### 用户命令（所有人可用）

| 命令 | 说明 |
| --- | --- |
| `订阅<主题ID>` | 订阅主题（当前群/私聊），如 `订阅公告` |
| `退订<主题ID>` | 退订主题，如 `退订公告` |
| `我的订阅` | 查看当前会话已订阅的主题 |
| `主题列表` | 查看全部推送主题 |

### 管理命令（仅超级用户）

| 命令 | 说明 |
| --- | --- |
| `推送新建 <ID> <名称> [描述...]` | 创建主题 |
| `推送删除 <ID>` | 删除主题及其订阅（代码注册的主题不可删除，仅可停用） |
| `推送启用 <ID>` / `推送停用 <ID>` | 启用/停用主题 |
| `推送订阅者 <ID>` | 查看某主题的订阅者 |
| `推送 <ID> <内容>` | 向某主题的全部订阅者推送消息 |
| `推送直发 <群号> <内容>` | 直接向指定群推送（测试/应急） |

## 其他插件接入

在目标插件的模块级代码中：

```python
from nonebot import require

require("ironsbot.plugins.push")

from ironsbot.plugins.push.models import Schedule
from ironsbot.plugins.push.service import register_topic, send_to_topic, send_to_targets

# 1. 注册主题（幂等；已存在时保留管理员设置的启用/可订阅状态）
register_topic(
    "db_sync_status",
    name="数据库同步状态",
    description="数据库同步异常的运维通知",
    allow_subscribe=False,  # 仅管理推送，不允许用户订阅
)

# 2. 编程主动推送（向主题全部订阅者）
await send_to_topic("db_sync_status", "数据库同步失败，请检查日志")

# 3. 直接推送到指定目标（不依赖订阅）
from nonebot_plugin_saa import TargetQQGroup

await send_to_targets(
    [TargetQQGroup(group_id=123456)],
    MessageFactory(Text("监控告警")),
)
```

### 定时推送

注册主题时传入 `Schedule` 与 `provider`（内容提供器）。每次触发时调用 `provider`，
返回 `None` 表示内容无变化、本次不推送；返回 `str`/`MessageFactory` 则推送给全部订阅者
（自动带 `dedup_key` 防止窗口内重复推送）。

```python
from ironsbot.plugins.push.models import Schedule
from ironsbot.plugins.push.service import register_topic


async def _daily_news_provider() -> str | None:
    """返回今日公告；内容无变化时返回 None。"""
    content = await fetch_daily_news()
    return content if content else None


register_topic(
    "news",
    name="公告",
    description="每日公告定时推送",
    schedule=Schedule(type="interval", hours=24),
    provider=_daily_news_provider,
)
```

`Schedule` 支持三种触发器：

- `Schedule(type="interval", minutes=..., hours=..., seconds=...)` — 固定间隔
- `Schedule(type="cron", cron="0 8 * * *", timezone="Asia/Shanghai")` — cron 表达式
- `Schedule(type="date", run_date=datetime(...))` — 单次执行

### 事件驱动推送

业务事件发生时直接调用 `send_to_topic` 推送。以 seer_data 的「数据库更新推送」为例：
在 `db_sync` 注册更新回调（`register_update_hook`），数据同步成功后在回调中推送。

```python
# ironsbot/plugins/seer_data/push_notify.py
from nonebot import logger

from ironsbot.plugins.push.service import register_topic, send_to_topic

PUSH_TOPIC_ID = "seer_db_update"

register_topic(
    PUSH_TOPIC_ID,
    name="数据库更新",
    description="赛尔号数据（seerapi / aliases）同步更新后推送通知",
)

async def notify_db_update(db_name: str, display_name: str | None = None) -> None:
    """推送数据库更新通知到订阅者。"""
    try:
        await send_to_topic(
            PUSH_TOPIC_ID,
            f"📢{display_name}已更新，可查询最新数据",
            dedup_key=f"seer_db_update:{db_name}",  # 窗口内同库重复更新只推一次
        )
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error("推送数据库更新通知失败")

# ironsbot/plugins/seer_data/db.py
# from ironsbot.plugins.db_sync import register_update_hook
# from .push_notify import build_updated_hook
# register_update_hook("seerapi", build_updated_hook("seerapi"))
```

`db_sync.register_update_hook(name, hook)` 在数据库同步成功（返回 `"updated"`）后、
`sync_database` 返回前依次执行注册的异步回调（首次启动同步也会触发）。

### 核心 API

见 `ironsbot/plugins/push/service.py`，主要函数：

- `register_topic(topic_id, *, name, description, allow_subscribe, enabled, schedule, provider)` — 注册主题
- `send_to_topic(topic_id, content, *, targets=None, dedup_key=None)` — 向主题订阅者推送
- `send_to_targets(targets, content, *, dedup_key=None)` — 直接向指定目标推送
- `subscribe(topic_id, target)` / `unsubscribe(topic_id, target)` — 订阅/退订
- `list_subscribers(topic_id)` / `list_topics()` / `get_topic(topic_id)` — 查询

## 数据存储

- 数据文件：`PUSH_DATA_DIR/push.db`（SQLite）
- 表：`topic`（主题）、`subscription`（订阅关系）、`pushrecord`（推送历史）
- 持久化内容：订阅关系、推送历史（含去重 key 与结果），任务定义不持久化（随代码注册重建）

## 测试

```bash
uv run python -m pytest tests/test_push_storage.py tests/test_push_commands_nonebug.py tests/test_seer_data_push_notify.py -q
```
