from ironsbot.runtime.matchers import MatcherRegistry

from .matchers import install as install_matchers
from .policies import setup_messaging_delivery_policies


def install(registry: MatcherRegistry) -> None:
    setup_messaging_delivery_policies()
    install_matchers(registry)
