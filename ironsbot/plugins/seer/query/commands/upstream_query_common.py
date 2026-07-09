# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: TC002
"""Shared upstream query matcher guards.

NoneBot evaluates rule annotations while registering matchers, so these imports
must stay available at runtime.
"""

from __future__ import annotations

from nonebot.adapters import Event
from nonebot.rule import Rule

from ironsbot.services.seer.query_guards import is_rank_query_text
from ironsbot.services.sendpic_fixed_image import FIXED_IMAGE_COMMANDS
from ironsbot.shared.plugin_system import dispatch_plugin, register_plugin

from .upstream_plugin import UPSTREAM_QUERY_PLUGIN_NAME, UpstreamQueryPlugin


async def _is_not_rank_query(event: Event) -> bool:
    return not is_rank_query_text(event.get_plaintext())


not_rank_query = Rule(_is_not_rank_query)


async def _is_not_fixed_image_command(event: Event) -> bool:
    return event.get_plaintext().strip() not in FIXED_IMAGE_COMMANDS


not_fixed_image_command = Rule(_is_not_fixed_image_command)


register_plugin(UpstreamQueryPlugin())


__all__ = [
    "UPSTREAM_QUERY_PLUGIN_NAME",
    "dispatch_plugin",
    "not_fixed_image_command",
    "not_rank_query",
]
