from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from .config import plugin_config

HistoryMessage = dict[str, str]

_HISTORY: dict[str, list[HistoryMessage]] = {}


def history_key(event: MessageEvent) -> str:
    if isinstance(event, GroupMessageEvent):
        return f"group:{event.group_id}:user:{event.user_id}"

    return f"private:{event.user_id}"


def trim_history(history: list[HistoryMessage]) -> list[HistoryMessage]:
    if plugin_config.ai_history_turns <= 0:
        return []

    max_messages = plugin_config.ai_history_turns * 2
    return history[-max_messages:]


def build_messages(
    history: list[HistoryMessage],
    prompt: str,
) -> list[HistoryMessage]:
    messages = [
        {
            "role": "system",
            "content": plugin_config.ai_prompt,
        }
    ]
    messages.extend(trim_history(history))
    messages.append({"role": "user", "content": prompt})
    return messages


def is_reset_prompt(prompt: str) -> bool:
    normalized = "".join(prompt.split())
    return any(
        normalized == "".join(command.split())
        for command in plugin_config.ai_reset_commands
    )


def get_history(key: str) -> list[HistoryMessage]:
    return _HISTORY.get(key, [])


def reset_history(key: str) -> None:
    _HISTORY.pop(key, None)


def append_turn(key: str, prompt: str, reply: str) -> None:
    history = get_history(key)
    _HISTORY[key] = trim_history(
        [
            *trim_history(history),
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": reply},
        ]
    )
