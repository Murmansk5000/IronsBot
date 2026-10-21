# SPDX-License-Identifier: MIT
"""Concise final reports without raw upload errors or signed URLs."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.core.outbound import SendResult
    from ironsbot.core.platform import ConversationRef


def delivery_failure_text(
    name: str,
    uid: int,
    dynamic_id: str,
    failures: dict[tuple[ConversationRef, str], SendResult],
) -> str:
    grouped: dict[ConversationRef, list[tuple[str, SendResult]]] = {}
    for (target, stage), result in failures.items():
        grouped.setdefault(target, []).append((stage, result))
    lines = []
    labels = {"link": "链接", "text": "正文", "image": "图片"}
    for target, results in grouped.items():
        stages = "、".join(
            labels.get(stage.split(":")[0], stage) for stage, _ in results
        )
        identities = dict.fromkeys(
            result.execution_identity
            for _, result in results
            if result.execution_identity is not None
        )
        identity = "、".join(item.describe() for item in identities)
        reasons = "；".join(
            f"{_failure_reason(result)}（已尝试{result.attempt_count}次）"
            for _, result in results
        )
        lines.append(
            f"失败目标：{'群' if target.kind == 'group' else '私聊'} {target.id}｜"
            f"失败阶段：{stages}｜执行机器人：{identity or '未确定'}\n{reasons}"
        )
    return (
        "⚠️ B站动态部分阶段发送失败\n"
        f"未完成 {len(failures)} 项；已完成内容不重发。其他成功阶段不受影响。\n"
        "结果不确定的项目不自动补发。\n"
        f"B站账号：{name}（UID：{uid}）\n动态ID：{dynamic_id}\n"
        + "\n".join(lines)
        + "\n仅列出重试耗尽或不可安全补发的项目。"
    )


def _failure_reason(result: SendResult) -> str:
    code = result.error_code or "未知原因"
    phase, _, reason = code.partition(":")
    phases = {
        "upload_prepare": "上传准备",
        "cos_put": "COS分片上传",
        "upload_confirm": "上传确认",
        "upload_complete": "上传完成",
        "message_submit": "消息提交",
        "media_prepare": "图片准备",
    }
    reasons = {
        "ReadTimeout": "响应超时",
        "ConnectTimeout": "连接超时",
        "ConnectError": "连接失败",
        "TimeoutError": "操作超时",
        "preceding_image_failed": "前序图片未成功，未继续发送",
    }
    if not reason:
        return reasons.get(code, code)
    return f"{phases.get(phase.split('[')[0], phase)}：{reasons.get(reason, reason)}"
