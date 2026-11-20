# SPDX-License-Identifier: MIT
"""Shared, bounded diagnostic snapshots; never fetch identities or raw payloads."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ironsbot.core.diagnostic_context import (
    current_diagnostic_operation,
    diagnostic_operation,
)
from ironsbot.core.message_origin import current_message_origin
from ironsbot.core.platform import Platform, reference_digest
from ironsbot.core.semantic_requests import current_semantic_request_trace
from ironsbot.core.time import TZ_CN

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from ironsbot.core.command_catalog import CommandContext
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.identity_principals import IdentityPrincipalService

logger = logging.getLogger(__name__)
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_AUTH = re.compile(
    r"(?im)\b(?:authorization|proxy-authorization|cookie)[\s\"':=]+[^\r\n]+"
)
_SECRET = re.compile(
    r"(?i)\b(?:authorization|bearer|token|secret|signature|password|api[_-]?key|"
    r"file_info|upload_id|app_secret)\b[\s\"':=]+[^\s,;<>]+"
)
_OPAQUE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]+|[A-Fa-f0-9]{24,})\b")
MAX_TEXT = 4000
MAX_NOTICE_TARGETS = 8
MAX_NOTICE_TEXT = 1800


@contextmanager
def query_diagnostic(action: str, command: str) -> Iterator[None]:
    summary = (
        command if action.startswith(("seer.", "operations.", "bilibili.")) else ""
    )
    with diagnostic_operation(action, summary):
        yield


def diagnostic_text(value: str, *, limit: int = MAX_TEXT) -> str:
    text = _AUTH.sub("[凭据已隐藏]", value[: MAX_TEXT * 2])
    text = _URL.sub("[链接已隐藏]", text)
    text = _SECRET.sub("[凭据已隐藏]", text)
    text = _OPAQUE.sub("[不透明标识已隐藏]", text)
    return "\n".join(" ".join(line.split()) for line in text.splitlines())[:limit]


@dataclass(frozen=True, slots=True)
class ErrorDiagnostic:
    operation: str
    stage: str
    origin: MessageInputContext | None = None
    task: str = ""
    error_id: str = field(default_factory=lambda: uuid4().hex[:12])
    occurred_at: datetime = field(default_factory=lambda: datetime.now(TZ_CN))
    command: str = ""
    target: str = ""
    entry: CommandContext | None = None
    targets: tuple[ConversationRef, ...] = ()
    trace_id: str = ""

    @classmethod
    def current(cls, operation: str, stage: str) -> ErrorDiagnostic:
        origin = current_message_origin()
        trace = current_semantic_request_trace()
        action, command = current_diagnostic_operation()
        target = ""
        if (
            origin is not None
            and trace is not None
            and trace.actor == origin.message.actor
            and trace.request.action.id.startswith(
                ("seer.", "operations.", "bilibili.")
            )
        ):
            operation = trace.request.action.label
            target = trace.request.target.display
            if trace.request.source.value in {"direct", "menu", "extension"}:
                command = operation + " " + target
        return cls(
            action or operation,
            stage,
            origin,
            command=command,
            target=target,
        )

    @classmethod
    def background(
        cls,
        operation: str,
        stage: str,
        *,
        task: str = "",
        targets: tuple[ConversationRef, ...] = (),
    ) -> ErrorDiagnostic:
        return cls(operation, stage, task=task or operation, targets=targets)


@dataclass(frozen=True, slots=True)
class DiagnosticFormatter:
    principals: IdentityPrincipalService | None = None
    group_aliases: Mapping[str, str] = field(default_factory=dict)
    user_aliases: Mapping[str, str] = field(default_factory=dict)
    bot_names: Mapping[str, str] = field(default_factory=dict)

    def describe(self, diagnostic: ErrorDiagnostic) -> str:
        stamp = diagnostic.occurred_at.astimezone(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"错误编号：{diagnostic.error_id}",
            f"发生时间：{stamp}（北京时间）",
            f"操作：{diagnostic_text(diagnostic.operation, limit=120)}",
            f"失败阶段：{diagnostic_text(diagnostic.stage, limit=80)}",
        ]
        if diagnostic.origin is None and diagnostic.entry is not None:
            entry = diagnostic.entry
            lines.extend(
                [
                    f"来源会话：{self.target_label(entry.conversation)}",
                    f"操作者摘要：{reference_digest(entry.actor.id)}",
                    "原消息：入口未提供，无法定位原消息",
                ]
            )
        elif diagnostic.origin is None:
            task = diagnostic_text(diagnostic.task or diagnostic.operation, limit=120)
            lines.append(f"后台任务：{task}")
            lines.append("触发消息：不适用（后台任务）")
        else:
            lines.extend(self._origin(diagnostic))
        if diagnostic.target:
            lines.append(f"业务目标：{diagnostic_text(diagnostic.target, limit=120)}")
        lines.extend(
            f"任务目标：{self.target_label(target)}"
            for target in diagnostic.targets[:MAX_NOTICE_TARGETS]
        )
        if len(diagnostic.targets) > MAX_NOTICE_TARGETS:
            lines.append(
                f"其余{len(diagnostic.targets) - MAX_NOTICE_TARGETS}个目标"
                "见同编号日志。"
            )
        if diagnostic.trace_id and re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", diagnostic.trace_id
        ):
            lines.append(f"Trace ID：{diagnostic.trace_id}")
        return "\n".join(lines)

    def target_label(self, target: ConversationRef) -> str:
        principal = (
            self.principals.conversation_principal(target) if self.principals else None
        )
        qq = (
            principal.id
            if principal is not None and principal.kind == "qq_group"
            else target.id
            if target.platform is Platform.ONEBOT and target.id.isdecimal()
            else ""
        )
        account = target.account_id or "未提供"
        name = self.bot_names.get(account, "名称未解析")
        account_label = account if account.isdecimal() else reference_digest(account)
        label = (
            f"{self.group_aliases.get(qq, '名称未解析')}（编号：{qq}）"
            if qq
            else f"未解析（摘要：{reference_digest(target.id)}）"
        )
        return (
            f"{target.platform.value}/{target.kind} {label}"
            f"｜账号：{name}/{account_label}"
        )

    def _origin(self, diagnostic: ErrorDiagnostic) -> list[str]:
        origin = diagnostic.origin
        assert origin is not None
        message = origin.message
        group = (
            self.principals.conversation_principal(message.conversation)
            if self.principals
            else None
        )
        actor = (
            self.principals.actor_principal(message.actor) if self.principals else None
        )
        is_onebot = message.platform is Platform.ONEBOT
        group_id = (
            group.id
            if group and group.kind == "qq_group"
            else message.conversation.id
            if is_onebot
            else ""
        )
        qq = (
            actor.id
            if actor and actor.kind == "qq"
            else message.actor.id
            if is_onebot
            else ""
        )
        group_id = group_id if group_id.isdecimal() else ""
        qq = qq if qq.isdecimal() else ""
        identity = origin.execution_identity
        account = origin.request_bot_id
        bot = (identity.display_name if identity else "") or self.bot_names.get(
            account, ""
        )
        account_label = (
            account
            if account.isdecimal()
            else reference_digest(account)
            if account
            else "未解析"
        )
        bot_label = f"{bot or '名称未解析'}（账号：{account_label}）"
        conversation = (
            f"群：{self.group_aliases.get(group_id, '名称未解析')}（群号：{group_id}）"
            if message.conversation.kind == "group" and group_id
            else f"群：未解析（摘要：{reference_digest(message.conversation.id)}）"
            if message.conversation.kind == "group"
            else "会话：私聊"
        )
        if group is not None and group.kind == "configured_group" and not group_id:
            conversation = f"群：{diagnostic_text(group.id, limit=80)}（群号未解析）"
        name = origin.actor_display_name or self.user_aliases.get(qq, "")
        user = (
            f"用户号：{qq}"
            if qq
            else f"用户号未解析，摘要：{reference_digest(message.actor.id)}"
        )
        command = diagnostic.command if message.conversation.kind == "group" else ""
        summary = (
            diagnostic_text(command, limit=160)
            if command
            else "正文不展示；见操作与业务目标"
        )
        return [
            f"平台：{message.platform.value}",
            f"执行机器人：{diagnostic_text(bot_label, limit=160)}",
            conversation,
            f"操作者：{diagnostic_text(name or '名称未解析', limit=80)}（{user}）",
            f"指令摘要：{summary}",
            f"原消息摘要：{reference_digest(message.message_id)}",
        ]

    def format(self, text: str, diagnostic: ErrorDiagnostic) -> str:
        result = self.describe(diagnostic) + "\n" + diagnostic_text(text)
        logger.error("Operational diagnostic:\n%s", result)
        if len(diagnostic.targets) > MAX_NOTICE_TARGETS:
            logger.error(
                "Diagnostic targets: error_id=%s targets=%s",
                diagnostic.error_id,
                tuple(self.target_label(target) for target in diagnostic.targets),
            )
        if len(result) > MAX_NOTICE_TEXT:
            return result[:MAX_NOTICE_TEXT] + f"\n详情见错误编号：{diagnostic.error_id}"
        return result
