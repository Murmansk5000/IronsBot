# SPDX-License-Identifier: MIT
"""Report final private push failures without retrying their payloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.platform import Platform, reference_digest

if TYPE_CHECKING:
    from ironsbot.services.messaging.admin_notice import AdminNoticeService
    from ironsbot.services.messaging.proactive_delivery import ProactiveDeliverySummary


async def report_private_push_failures(
    notices: AdminNoticeService,
    action_name: str,
    summary: ProactiveDeliverySummary,
) -> None:
    # Bilibili reports failed stages itself, with dynamic and stage context.
    if action_name.startswith("Bilibili "):
        return
    results = dict(summary.results)
    lines: list[str] = []
    for conversation in summary.failed:
        if conversation.kind != "private":
            continue
        receipt = results.get(conversation)
        if conversation.platform is Platform.ONEBOT:
            target = f"用户 {conversation.id}"
        else:
            target = (
                f"AppID {conversation.account_id} / "
                f"OpenID {reference_digest(conversation.id)}"
            )
        identity = receipt.execution_identity if receipt is not None else None
        status = (
            "发送结果不确定"
            if conversation in summary.uncertain
            else "发送失败"
            if receipt is not None and receipt.attempted
            else "未发送（路由或平台不可用）"
        )
        code = (receipt.error_code or "未知") if receipt is not None else "无回执"
        lines.append(
            f"失败目标：{target}\n状态：{status}（{code[:80]}）\n"
            f"执行机器人：{identity.describe() if identity else '未确定'}"
        )
    if not lines:
        return
    await notices.send_private_to_superusers(
        "⚠️ 私聊推送未完成\n"
        f"任务：{action_name}\n"
        + "\n".join(lines),
        subscription_key="admin_notice",
        action_name="private push failure notice",
        interval_seconds=0,
    )
