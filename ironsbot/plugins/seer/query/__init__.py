# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.runtime.matchers import MatcherRegistry
from ironsbot.services.operations.headless import HeadlessService

from .commands import install as install_commands
from .group import SeerMatcherGroup


def install(registry: MatcherRegistry, headless: HeadlessService) -> None:
    install_commands(SeerMatcherGroup(registry, headless))
