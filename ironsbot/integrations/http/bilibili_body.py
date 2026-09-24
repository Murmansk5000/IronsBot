"""Decode full Bilibili Opus and article bodies for dynamic detail responses."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def article_id(payload: object) -> int | None:
    article = _major(payload).get("article")
    value = article.get("id") if isinstance(article, Mapping) else None
    if not isinstance(value, (int, str)) or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def article_body(payload: object) -> str:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    content = data.get("content") if isinstance(data, Mapping) else None
    return content.strip() if isinstance(content, str) else ""


def opus_summary_is_truncated(payload: object) -> bool:
    opus = _major(payload).get("opus")
    summary = opus.get("summary") if isinstance(opus, Mapping) else None
    return isinstance(summary, Mapping) and summary.get("has_more") is True


def opus_body(payload: object) -> str:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    item = data.get("item") if isinstance(data, Mapping) else None
    modules = item.get("modules") if isinstance(item, Mapping) else None
    if not isinstance(modules, list):
        return ""
    pieces = []
    for module in modules:
        content = module.get("module_content") if isinstance(module, Mapping) else None
        paragraphs = content.get("paragraphs") if isinstance(content, Mapping) else None
        if not isinstance(paragraphs, list):
            continue
        pieces.extend(
            piece for paragraph in paragraphs if (piece := _paragraph_text(paragraph))
        )
    return "\n".join(pieces)


def replace_opus_summary(payload: object, body: str) -> object:
    resolved = deepcopy(payload)
    summary = _opus_summary(resolved)
    if not isinstance(summary, dict):
        return payload
    current = summary.get("text")
    if isinstance(current, str) and len(body) <= len(current):
        return payload
    summary["text"] = body
    summary["has_more"] = False
    return resolved


def replace_article_body(payload: object, body: str) -> object:
    resolved = deepcopy(payload)
    article = _major(resolved).get("article")
    if not isinstance(article, dict):
        return payload
    current = article.get("desc")
    if isinstance(current, str) and len(body) <= len(current):
        return payload
    article["desc"] = body
    article["_ironsbot_body_hydrated"] = True
    return resolved


def _major(payload: object) -> Mapping[str, Any]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    item = data.get("item") if isinstance(data, Mapping) else None
    modules = item.get("modules") if isinstance(item, Mapping) else None
    dynamic = modules.get("module_dynamic") if isinstance(modules, Mapping) else None
    major = dynamic.get("major") if isinstance(dynamic, Mapping) else None
    return major if isinstance(major, Mapping) else {}


def _opus_summary(payload: object) -> object:
    opus = _major(payload).get("opus")
    return opus.get("summary") if isinstance(opus, Mapping) else None


def _paragraph_text(paragraph: object) -> str:
    text = paragraph.get("text") if isinstance(paragraph, Mapping) else None
    nodes = text.get("nodes") if isinstance(text, Mapping) else None
    if not isinstance(nodes, list):
        return ""
    words = []
    for node in nodes:
        word = node.get("word") if isinstance(node, Mapping) else None
        value = word.get("words") if isinstance(word, Mapping) else None
        if isinstance(value, str):
            words.append(value)
    return "".join(words).strip()
