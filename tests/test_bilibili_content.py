from __future__ import annotations

import pytest

from ironsbot.services.bilibili.content import (
    SUMMARY_MAX_ATTEMPTS,
    DynamicContentCompactor,
)


@pytest.mark.asyncio
async def test_compactor_uses_keyword_summary_contract() -> None:
    calls: list[tuple[str, int]] = []

    async def summarize(text: str, *, max_chars: int) -> str:
        calls.append((text, max_chars))
        return "有效摘要"

    result = await DynamicContentCompactor(
        summarizer=summarize,
        content_max_chars=4,
        summary_max_chars=8,
        use_ai=True,
    ).compact("一段很长的动态正文")

    assert result is not None
    assert result.text == "有效摘要"
    assert result.generated_by_ai
    assert result.display_text == "本条动态文本过长，AI总结如下：\n有效摘要"
    assert calls == [("一段很长的动态正文", 8)]


@pytest.mark.asyncio
async def test_compactor_retries_oversized_summary_then_uses_excerpt() -> None:
    calls = 0

    async def summarize(_text: str, *, max_chars: int) -> str:
        nonlocal calls
        calls += 1
        return "过长" * max_chars

    result = await DynamicContentCompactor(
        summarizer=summarize,
        content_max_chars=4,
        summary_max_chars=6,
        use_ai=True,
    ).compact("原始正文足够长")

    assert result is not None
    assert result.text == "原始正文足够"
    assert not result.generated_by_ai
    assert result.display_text == result.text
    assert calls == SUMMARY_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_compactor_falls_back_when_ai_raises() -> None:
    calls = 0

    async def fail(_text: str, *, max_chars: int) -> str:
        nonlocal calls
        del max_chars
        calls += 1
        raise RuntimeError

    result = await DynamicContentCompactor(
        summarizer=fail,
        content_max_chars=4,
        summary_max_chars=6,
        use_ai=True,
    ).compact("原始正文足够长")

    assert result is not None
    assert result.text == "原始正文足够"
    assert not result.generated_by_ai
    assert calls == SUMMARY_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_compactor_leaves_short_content_unchanged() -> None:
    async def unexpected(_text: str, *, max_chars: int) -> str:
        del max_chars
        raise AssertionError

    result = await DynamicContentCompactor(
        summarizer=unexpected,
        content_max_chars=10,
        summary_max_chars=6,
        use_ai=True,
    ).compact("短正文")

    assert result is None
