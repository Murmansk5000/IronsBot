HistoryMessage = dict[str, str]


def trim_history(
    history: list[HistoryMessage],
    history_turns: int,
) -> list[HistoryMessage]:
    if history_turns <= 0:
        return []

    max_messages = history_turns * 2
    return history[-max_messages:]


def build_messages(
    *,
    system_prompt: str,
    history_turns: int,
    history: list[HistoryMessage],
    prompt: str,
    memory: list[HistoryMessage] | None = None,
) -> list[HistoryMessage]:
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]
    memory_text = format_memory(memory or [])
    if memory_text:
        messages.append(
            {
                "role": "system",
                "content": memory_text,
            }
        )
    messages.extend(trim_history(history, history_turns))
    messages.append({"role": "user", "content": prompt})
    return messages


def format_memory(memory: list[HistoryMessage]) -> str:
    if not memory:
        return ""

    lines = [
        "以下是这个 QQ 用户过去和你对话时留下的长期记忆。",
        "这些信息可能来自私聊或不同群聊，只能作为理解用户偏好和上下文的参考；如果和当前消息冲突，以当前消息为准。",
    ]
    for message in memory:
        role = "用户" if message.get("role") == "user" else "助手"
        content = message.get("content", "").strip()
        if content:
            lines.append(f"{role}：{content}")

    return "\n".join(lines)


def append_turn(
    histories: dict[str, list[HistoryMessage]],
    key: str,
    prompt: str,
    reply: str,
    history_turns: int,
) -> None:
    history = histories.get(key, [])
    histories[key] = trim_history(
        [
            *trim_history(history, history_turns),
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": reply},
        ],
        history_turns,
    )
