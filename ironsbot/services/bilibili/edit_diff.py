# SPDX-License-Identifier: MIT
"""Escapable text fragments and ordered media-change presentation models."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest

from .revisions import media_identity

_TOKENS = re.compile(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)|[\s\S]")


@dataclass(frozen=True, slots=True)
class TextChange:
    text: str
    kind: str


def text_changes(before: str, after: str) -> tuple[TextChange, ...]:
    left, right = _TOKENS.findall(before), _TOKENS.findall(after)
    result = []
    for kind, start, end, new_start, new_end in SequenceMatcher(
        None, left, right, autojunk=False
    ).get_opcodes():
        if kind == "equal":
            result.append(TextChange("".join(left[start:end]), "equal"))
        else:
            if kind in {"delete", "replace"}:
                result.append(TextChange("".join(left[start:end]), "delete"))
            if kind in {"insert", "replace"}:
                result.append(TextChange("".join(right[new_start:new_end]), "insert"))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class MediaChange:
    before_index: int | None
    after_index: int | None
    label: str
    moved: bool = False


def media_changes(before: list[str], after: list[str]) -> tuple[MediaChange, ...]:
    available: dict[str, deque[int]] = defaultdict(deque)
    for index, url in enumerate(before):
        available[media_identity(url)].append(index)
    matched_old, matched_new, changes = set(), set(), []
    for new_index, url in enumerate(after):
        if available[media_identity(url)]:
            old_index = available[media_identity(url)].popleft()
            matched_old.add(old_index)
            matched_new.add(new_index)
            if old_index != new_index:
                changes.append(
                    MediaChange(
                        old_index,
                        new_index,
                        f"图片顺序：第{old_index + 1}张 → 第{new_index + 1}张",
                        moved=True,
                    )
                )
    missing = [i for i in range(len(before)) if i not in matched_old]
    added = [i for i in range(len(after)) if i not in matched_new]
    for old_index, new_index in zip_longest(missing, added):
        label = (
            f"删除第{old_index + 1}张图片"
            if new_index is None
            else f"新增第{new_index + 1}张图片"
            if old_index is None
            else f"图片替换：第{old_index + 1}张 → 第{new_index + 1}张"
        )
        changes.append(MediaChange(old_index, new_index, label))
    return tuple(changes)


@dataclass(frozen=True, slots=True)
class ImageComparison:
    panels: tuple[tuple[bytes | None, bytes | None], ...]
    note: str
    identical: bool = False
