# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.runtime.matchers import MatcherRegistry
from ironsbot.services.admin_priority import AdminPriorityService
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.shared.features import FeatureService

from .commands import install as install_commands
from .group import SeerMatcherGroup


def install(
    registry: MatcherRegistry,
    headless: HeadlessService,
    features: FeatureService,
    priority: AdminPriorityService,
) -> None:
    install_commands(SeerMatcherGroup(registry, headless, features, priority))
