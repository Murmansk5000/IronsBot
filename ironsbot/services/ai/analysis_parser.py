# SPDX-License-Identifier: MIT
"""赛尔号魂印/技能描述标签解析器

将包含 ``[color=...]`` 和 ``[sprite name=...]`` 标签的Analyze描述文本
解析为结构化数据。
"""

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field

_TAG_RE = re.compile(
    r"\[color=(#[0-9a-fA-F]{6})\]"
    r"|\[/color\]"
    r"|\[sprite name=(\w+)\]"
    r"|([^\[]+|\[)"
)
_ID_SUFFIX_RE = re.compile(r"\((\d+)\)$")


@dataclass(slots=True)
class TextSegment:
    """一段带有可选颜色标记的文本片段

    ``colors`` 保存该片段所处的完整颜色栈快照（外层在前，内层在后），
    同一个 ``[/color]`` 闭合多个嵌套标签时，文本会同时关联所有活跃颜色。

    特别地，当描述中显式指定了片段词条 ID 时，该对象将携带该 ID。
    """

    text: str
    colors: tuple[str, ...] = ()
    id: int | None = None


@dataclass(slots=True)
class DescLine:
    """描述中的一行"""

    sprite: str | None = None
    indent: int = 0
    segments: list[TextSegment] = field(default_factory=list)

    @property
    def plain_text(self) -> str:
        return "".join(seg.text for seg in self.segments)

    def colored_texts(self, color: str) -> list[str]:
        """返回该行中包含指定颜色的所有文本"""
        return [seg.text for seg in self.segments if color in seg.colors]

    def to_html(
        self,
        styles: dict[str, Callable[[str], str]] | None = None,
    ) -> str:
        """将该行转为 HTML 文本，通过工厂函数自定义各颜色的样式。

        当一个片段同时关联多个颜色时，匹配的工厂函数会由内向外依次嵌套。

        Args:
            styles: 颜色值到工厂函数的映射。工厂函数接收已转义的文本，
                返回包含样式的 HTML 片段。未在映射中的颜色按纯文本输出。
                为 ``None`` 时所有文本均按纯文本输出。
        """
        parts: list[str] = []
        for seg in self.segments:
            result = html.escape(seg.text)
            if seg.colors and styles:
                seen: set[str] = set()
                for color in reversed(seg.colors):
                    if color not in seen and (styler := styles.get(color)):
                        result = styler(result)
                        seen.add(color)
            parts.append(result)
        return "".join(parts)


def _parse_desc_line(raw: str) -> DescLine:
    stripped = raw.lstrip()
    indent = len(raw) - len(stripped)
    line = DescLine(indent=indent)
    color_stack: list[str] = []
    # 连续打开的颜色标签数量；遇到文本时保存为 last_batch，
    # [/color] 依此弹出整个批次而非仅栈顶一个。
    current_opens = 0
    last_batch = 0

    for m in _TAG_RE.finditer(stripped):
        if m.group(1) is not None:
            color_stack.append(m.group(1))
            current_opens += 1
        elif m.group(0) == "[/color]":
            pop_count = min(max(1, last_batch), len(color_stack))
            for _ in range(pop_count):
                color_stack.pop()
            last_batch = 0
            current_opens = 0
        elif m.group(2) is not None:
            line.sprite = m.group(2)
        elif m.group(3) is not None:
            last_batch = current_opens
            current_opens = 0
            cur = tuple(set(color_stack))
            text = m.group(3)
            seg_id: int | None = None
            if id_match := _ID_SUFFIX_RE.search(text):
                seg_id = int(id_match.group(1))
                text = text[: id_match.start()]
            can_merge = (
                line.segments
                and line.segments[-1].colors == cur
                and line.segments[-1].id is None
                and seg_id is None
            )
            if can_merge:
                line.segments[-1].text += text
            else:
                line.segments.append(
                    TextSegment(text=text, colors=cur, id=seg_id)
                )

    return line


class AnalyzeDescParser:
    """赛尔号Analyze描述标签解析器

    将包含 ``[color=...]`` 和 ``[sprite name=...]`` 标签的描述文本
    解析为结构化的 :class:`DescLine` 列表。行之间以 ``|`` 分隔。
    """

    def __init__(self, desc: str) -> None:
        self.desc = desc
        self.lines: list[DescLine] = [_parse_desc_line(raw) for raw in desc.split("|")]

    def lines_by_sprite(self, sprite: str) -> list[DescLine]:
        """返回所有匹配指定 sprite 名称的行"""
        return [line for line in self.lines if line.sprite == sprite]

    @property
    def sprites(self) -> set[str]:
        """描述中出现的所有 sprite 名称"""
        return {line.sprite for line in self.lines if line.sprite}

    @property
    def segments(self) -> list[TextSegment]:
        """描述中出现的所有文本片段"""
        return [seg for line in self.lines for seg in line.segments]

    @property
    def segments_with_id(self) -> set[int]:
        """描述中出现的所有词条 ID"""
        return {seg.id for seg in self.segments if seg.id}

    @property
    def colors(self) -> set[str]:
        """描述中出现的所有颜色值"""
        return {c for line in self.lines for seg in line.segments for c in seg.colors}

    def to_plain_text(self, line_separator: str = "\n") -> str:
        """将完整描述转为不带任何标签的纯文本。"""
        return line_separator.join(line.plain_text for line in self.lines)

    def to_html(
        self,
        styles: dict[str, Callable[[str], str]] | None = None,
        line_separator: str = "<br>",
    ) -> str:
        """将完整描述转为 HTML 文本，通过工厂函数自定义各颜色的样式。

        Args:
            styles: 颜色值到工厂函数的映射。工厂函数接收已转义的文本，
                返回包含样式的 HTML 片段。未在映射中的颜色按纯文本输出。
                为 ``None`` 时所有文本均按纯文本输出。
            line_separator: 行之间的分隔符，默认 ``<br>``。
        """
        return line_separator.join(line.to_html(styles) for line in self.lines)
