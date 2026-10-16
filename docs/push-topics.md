# 通用主题推送

主题推送使用独立功能 `push_topics`，与固定文本、B站和活动提醒共用现有发送、路由、TD 偏好及调度设施。开启该功能不会自动订阅主题，也不会修改已有群的权限。

## 口令

```text
推送列表
推送新建 公告 群公告
订阅公告
我的订阅
推送 公告 本次公告内容
退订公告
推送停用 公告
推送启用 公告
推送订阅者 公告
推送直发 公告 群:群别名 本次公告内容
推送直发 公告 私聊:用户别名 本次公告内容
推送删除 公告
```

超级管理员可以管理主题、查看订阅者及发送广播或直发。群主、群管理员和超级管理员可以修改本群订阅；私聊用户只修改自己的订阅。普通群成员可以查看主题及当前群订阅。

短口令 `订阅公告`、`退订公告` 仅在该主题存在时认领。也可以使用明确形式 `订阅主题 公告`、`退订主题 公告`；不存在的主题会提示错误。既有战队订阅等口令保持各自归属。

TD 菜单显示当前会话已经显式订阅的主题，可以退订或恢复。停用主题保留订阅和历史，停止调度及新的投递；删除主题取消其调度并移除主题记录。代码注册的主题可以停用，不能通过口令删除。

直发只解析明确给出的目标，选择与发起会话相同平台及账号的端点，然后经过现有路由。缺少对应端点时不会改用其他机器人。直发仍检查目标功能、黑名单、TD 退订及平台发送能力。

## 程序注册

组合根或应用生命周期中通过 `resources.messaging.topics` 取得服务，并显式注册提供器；无需新的平台发送器。

```python
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.messaging.topics import TopicPublication, TopicSchedule


async def provide_announcement() -> TopicPublication | None:
    return TopicPublication(
        OutboundMessage.from_text("本次公告内容"),
        dedup_key="announcement:stable-event-id",
    )


await topics.register(
    "公告",
    "群公告",
    (
        TopicSchedule("daily", "cron", provide_announcement, {"hour": 12}),
        TopicSchedule("periodic", "interval", provide_announcement, {"minutes": 30}),
    ),
)
```

`date` 调度使用带时区的 `run_date: datetime`。提供器返回 `None` 表示本次无内容。每次启动重新注册代码提供器，主题启停和订阅由数据库恢复；调度使用稳定任务 ID 替换注册，单实例执行并合并误点，不批量补发停机期间的任务。过期的 `date` 任务不会重新运行。关闭服务移除主题任务。

`await topics.publish(key, TopicPublication(...))` 向显式订阅者广播；`targets=(ConversationRef(...),)` 可指定类型明确的目标，仍执行相同授权和路由。发送结果按 `delivered`、`failed`、`uncertain`、`skipped`、`duplicate` 统计。

## 状态与投递保证

状态存放在现有 `paths.runtime_state`，使用独立 SQLite 迁移命名空间 `push_topics`。首次正常启动自动创建新表，无需修改旧订阅键或迁移旧订阅数据。

每个主题通过 `store.history(key)` 获取最近 500 条逐目标投递记录。显式去重键按主题和实际选定的发送端点保留 3600 秒；近期去重记录独立于显示的 500 条历史上限，避免高频发送挤掉去重证据。

只有确认送达才记为成功。发送前写入原子 claim；不确定送达和进程中断遗留的 pending claim 均阻止同一去重键在窗口内重新发送。明确失败可以由后续显式调用再次尝试。传输重试沿用公共 delivery 的失败分类，不盲目重发不确定结果。

所有命令使用同一解析器和业务处理器，QQ 官方与 OneBot 共享功能、权限和行为。此功能不需要新增环境变量或 Unraid 项目；部署时只需按需在现有 Feature 配置中加入 `push_topics`。
