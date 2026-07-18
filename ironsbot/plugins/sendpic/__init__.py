from ironsbot.config.models.message import SendpicBehaviorConfig
from ironsbot.runtime.matchers import MatcherRegistry

from .fixed_images import install as install_fixed_images
from .matchers import install as install_configured_images


def install(
    registry: MatcherRegistry,
    config: SendpicBehaviorConfig,
    cnb_token: str | None,
) -> None:
    install_fixed_images(registry)
    install_configured_images(registry, config, cnb_token)


__all__ = ["install"]
