# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.ai.client import AiRequestTimeoutError
from ironsbot.services.ai.history import (
    HistoryMessage,
    append_turn,
    build_messages,
)
from ironsbot.services.ai.intent import (
    build_intent_prompt,
    contains_any_keyword,
    excluded_by_command,
    excluded_by_context,
    format_action_template,
    is_action_allowed,
    is_ai_intent_allowed,
    passes_action_prefilter,
    reply_is_yes,
)
from ironsbot.services.ai.memory import AiMemoryTurn, trim_memory_chars
from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

if TYPE_CHECKING:
    from ironsbot.config.models.ai import AiConfig
    from ironsbot.core.features import FeatureService
    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.services.ai.client import AiCompletionClient
    from ironsbot.services.ai.memory import AiMemoryStore
    from ironsbot.services.messaging.admin_notice import AdminNoticeService

REQUEST_FAILED_REPLY = "AI接口请求失败，我已经通知超级管理员。"
EMPTY_REPLY = "AI没有返回有效内容，请稍后再试。"
MISSING_KEY_REPLY = "AI聊天还没有配置 API Key。请先设置 IRONSBOT_AI_KEY。"
TIMEOUT_REPLY = "AI接口响应超时，我已经通知超级管理员。"
UNEXPECTED_ERROR_REPLY = "AI聊天出错了，我已经通知超级管理员。"
TEAM_ACTIONS = frozenset({"team_recommend", "team_resource"})
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Completion:
    reply: str = ""
    error_reply: str = ""


class AiService:
    def __init__(  # noqa: PLR0913 - dependencies stay explicit
        self,
        config: AiConfig,
        features: FeatureService,
        admin_notices: AdminNoticeService,
        team_resource_commands: tuple[str, ...],
        completion: AiCompletionClient,
        memory: AiMemoryStore | None = None,
    ) -> None:
        self._config = config
        self._features = features
        self._admin_notices = admin_notices
        self._team_resource_commands = team_resource_commands
        self._completion = completion
        self._memory = memory
        self._history: dict[str, list[HistoryMessage]] = {}
        self._notice_limiter = SlidingWindowRateLimiter()

    @property
    def waiting_notice(self) -> bool:
        return self._config.waiting_notice and bool(self._config.api_key.strip())

    def _can_show_admin_notice(
        self,
        user_id: int,
        group_id: int | None,
    ) -> bool:
        return self._features.is_superuser(user_id) or (
            group_id is not None
            and self._features.group_has_feature(group_id, "admin_notice")
        )

    async def chat_reply(
        self,
        *,
        user_id: int,
        group_id: int | None,
        prompt: str,
        source_context: str | None = None,
    ) -> str | None:
        key = _chat_key(user_id, group_id)
        history = self._history.get(key, [])
        completion = await self._complete(
            prompt,
            history,
            self._load_memory(user_id, key, exclude_current_session=bool(history)),
            source_context,
        )
        if completion.error_reply:
            return (
                completion.error_reply
                if self._can_show_admin_notice(user_id, group_id)
                else None
            )

        append_turn(
            self._history,
            key,
            prompt,
            completion.reply,
            self._config.history_turns,
        )
        self._record_memory(user_id, group_id, key, prompt, completion.reply)
        return completion.reply

    async def classify_intent(
        self,
        text: str,
        *,
        user_id: int,
        group_id: int | None = None,
        source_context: str | None = None,
    ) -> AiIntentAction | None:
        if (
            not self._config.intent_actions_enabled
            or not self._config.api_key.strip()
            or not is_ai_intent_allowed(self._features, user_id, group_id)
        ):
            return None

        text = text.strip()
        if not text:
            return None

        for action in self._config.intent_actions.values():
            if not self._action_matches(action, text, user_id, group_id):
                continue

            completion = await self._complete(
                build_intent_prompt(action, text),
                [],
                [],
                source_context,
            )
            if not completion.reply:
                return None

            logger.info(
                "AI intent action %s classified %s: %r",
                action.id or "<unnamed>",
                user_id,
                completion.reply,
            )
            if reply_is_yes(completion.reply):
                return action

        return None

    async def run_reply_action(
        self,
        action: AiIntentAction,
        text: str,
        *,
        source_context: str | None = None,
    ) -> str | None:
        completion = await self._complete(
            format_action_template(action, action.reply_prompt, text.strip()),
            [],
            [],
            source_context,
        )
        return completion.reply or None

    @staticmethod
    def is_team_action(action: AiIntentAction) -> bool:
        return action.action in TEAM_ACTIONS

    def _action_matches(
        self,
        action: AiIntentAction,
        text: str,
        user_id: int,
        group_id: int | None,
    ) -> bool:
        return (
            action.enabled
            and is_action_allowed(self._features, user_id, group_id, action)
            and contains_any_keyword(text, action.keywords)
            and passes_action_prefilter(text, action)
            and not excluded_by_command(
                text,
                action,
                self._team_resource_commands,
            )
            and not excluded_by_context(text, action)
        )

    async def _complete(
        self,
        prompt: str,
        history: list[HistoryMessage],
        memory: list[HistoryMessage],
        source_context: str | None,
    ) -> _Completion:
        if not self._config.api_key.strip():
            await self._notify_admin_once(
                "missing_api_key",
                _append_notice_source(
                    "AI聊天还没有配置 API Key。\n"
                    "请在 Unraid 容器变量或 .env.prod 中设置 "
                    "IRONSBOT_AI_KEY。",
                    source_context,
                ),
            )
            return _Completion(error_reply=MISSING_KEY_REPLY)

        messages = build_messages(
            system_prompt=self._config.prompt,
            history_turns=self._config.history_turns,
            history=history,
            prompt=prompt,
            memory=memory,
        )
        try:
            result = await self._completion.complete(messages)
        except AiRequestTimeoutError:
            logger.warning("AI chat API timed out")
            await self._notify_admin_once(
                "timeout",
                _append_notice_source(
                    "AI聊天接口响应超时。\n"
                    f"接口：{self._config.base_url}\n"
                    f"超时时间：{self._config.timeout} 秒\n"
                    "请检查网络或适当调大 ai.timeout。",
                    source_context,
                ),
            )
            return _Completion(error_reply=TIMEOUT_REPLY)
        except Exception as exc:
            logger.exception("AI chat failed")
            await self._notify_admin_once(
                "unexpected",
                _append_notice_source(
                    "AI聊天处理失败。\n"
                    f"错误：{exc}\n"
                    "请查看容器日志确认具体原因。",
                    source_context,
                ),
            )
            return _Completion(error_reply=UNEXPECTED_ERROR_REPLY)

        if result.ok:
            return _Completion(
                reply=_truncate_reply(
                    result.reply,
                    self._config.max_reply_chars,
                )
            )

        if result.error_kind == "empty_reply":
            await self._notify_admin_once(
                "empty_reply",
                _append_notice_source(
                    "AI聊天接口返回了空内容。\n"
                    f"模型：{self._config.model}\n"
                    "请检查模型配置或稍后重试。",
                    source_context,
                ),
            )
            return _Completion(error_reply=EMPTY_REPLY)

        logger.warning(
            "AI chat API failed: HTTP %s, %s",
            result.status_code,
            result.error_detail,
        )
        await self._notify_admin_once(
            (
                f"http_{result.status_code}"
                if result.error_kind == "http"
                else str(result.error_kind)
            ),
            _append_notice_source(
                "AI聊天接口异常。\n"
                f"类型：{result.error_title}\n"
                f"HTTP：{result.status_code}\n"
                f"模型：{self._config.model}\n"
                f"接口：{self._config.base_url}\n"
                f"详情：{result.error_detail}\n"
                "请检查 IRONSBOT_AI_KEY、账户额度、模型名和网络连接。",
                source_context,
            ),
        )
        return _Completion(error_reply=REQUEST_FAILED_REPLY)

    def _load_memory(
        self,
        user_id: int,
        key: str,
        *,
        exclude_current_session: bool,
    ) -> list[HistoryMessage]:
        if (
            not self._config.memory
            or self._config.memory_turns <= 0
            or self._memory is None
        ):
            return []
        return trim_memory_chars(
            self._memory.load(
                user_id=user_id,
                current_session_key=key,
                exclude_current_session=exclude_current_session,
                limit=self._config.memory_turns * 2,
            ),
            self._config.memory_max_chars,
        )

    def _record_memory(
        self,
        user_id: int,
        group_id: int | None,
        key: str,
        prompt: str,
        reply: str,
    ) -> None:
        if (
            not self._config.memory
            or self._config.memory_turns <= 0
            or self._memory is None
        ):
            return
        chat_scope, chat_id = (
            ("group", group_id)
            if group_id is not None
            else ("private", user_id)
        )
        self._memory.append(
            AiMemoryTurn(
                user_id,
                key,
                chat_scope,
                chat_id,
                prompt,
                reply,
            )
        )

    async def _notify_admin_once(self, key: str, message: str) -> None:
        if (
            self._notice_limiter.hit(
                "admin_notice",
                key,
                window_seconds=self._config.admin_notice_cooldown_seconds,
                max_events=1,
            )
            < 0
        ):
            return
        await self._admin_notices.send(
            message,
            subscription_key="ai_chat_error_notice",
            action_name="AI chat error notice",
        )


def _chat_key(user_id: int, group_id: int | None) -> str:
    if group_id is not None:
        return f"group:{group_id}:user:{user_id}"
    return f"private:{user_id}"


def _append_notice_source(message: str, source_context: str | None) -> str:
    source = (source_context or "").strip()
    return f"{message.rstrip()}\n\n触发来源：\n{source}" if source else message


def _truncate_reply(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n\n（回复过长，已截断）"
