# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

DEFAULT_SELECTION_FOOTER = "💬 输入序号选择"
HELP_SELECTION_FOOTER = "💬 直接发送序号查看详细帮助"
TOGGLE_SELECTION_FOOTER = "✅ 已订阅 · ❌ 已退订，输入序号切换"
EXIT_SELECTION_LINE = "0.【退出】"


@dataclass(frozen=True, slots=True)
class SelectionMenuItem:
    label: str
    prefix: str = ""
    detail_lines: tuple[str, ...] = ()
    is_sub_item: bool = False


@dataclass(frozen=True, slots=True)
class SelectionMenuSection:
    title: str
    items: tuple[SelectionMenuItem | str, ...]


MenuEntry: TypeAlias = SelectionMenuItem | SelectionMenuSection | str


@dataclass(frozen=True, slots=True)
class SelectionMenu:
    title: str
    items: tuple[MenuEntry, ...]
    intro_lines: tuple[str, ...] = ()
    footer: str | None = DEFAULT_SELECTION_FOOTER
    include_exit: bool = True


def format_selection_menu(
    menu: SelectionMenu | None = None,
    *,
    title: str = "",
    items: tuple[MenuEntry, ...] = (),
    intro_lines: tuple[str, ...] = (),
    footer: str | None = DEFAULT_SELECTION_FOOTER,
) -> str:
    if menu is None:
        menu = SelectionMenu(
            title=title,
            items=items,
            intro_lines=intro_lines,
            footer=footer,
        )

    lines: list[str] = []
    _append_text_block(lines, menu.title)
    _extend_lines(lines, menu.intro_lines)

    index = 1
    for entry in menu.items:
        if isinstance(entry, SelectionMenuSection):
            _append_section_title(lines, entry.title)
            for item in entry.items:
                lines.extend(_format_item(_coerce_item(item), index))
                index += 1
            continue

        lines.extend(_format_item(_coerce_item(entry), index))
        index += 1

    if menu.include_exit:
        lines.append(EXIT_SELECTION_LINE)

    if menu.footer:
        if lines and lines[-1] != "":
            lines.append("")
        _append_text_block(lines, menu.footer)

    return "\n".join(lines)


def _coerce_item(item: SelectionMenuItem | str) -> SelectionMenuItem:
    if isinstance(item, SelectionMenuItem):
        return item
    return SelectionMenuItem(label=item)


def _format_item(item: SelectionMenuItem, index: int) -> list[str]:
    prefix = f"{item.prefix} " if item.prefix else ""
    sub_prefix = " ↳ " if item.is_sub_item else ""
    lines = [f"{sub_prefix}{index}. {prefix}{item.label}"]
    lines.extend(f"   {line}" for line in item.detail_lines)
    return lines


def _append_section_title(lines: list[str], title: str) -> None:
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(f"【{title}】")


def _append_text_block(lines: list[str], text: str) -> None:
    _extend_lines(lines, tuple(text.strip("\n").splitlines()))


def _extend_lines(lines: list[str], new_lines: tuple[str, ...]) -> None:
    lines.extend(line for line in new_lines if line != "")
