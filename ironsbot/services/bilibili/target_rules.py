from ironsbot.core.bilibili import (
    BiliConfig,
    BiliPushMode,
    BiliPushTargetConfig,
)

from .target_models import BiliTargetRule


def build_bili_target_rule(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> BiliTargetRule:
    aliases = frozenset([*config.push.accounts, *target_config.accounts])
    return BiliTargetRule(
        aliases=aliases,
        uids=frozenset(config.accounts[alias].uid for alias in aliases),
        default_mode=config.push.mode,
        target_mode=target_config.mode,
        modes={
            **_resolve_modes(config.push.modes, config),
            **_resolve_modes(target_config.modes, config),
        },
    )


def default_bili_target_rule(config: BiliConfig) -> BiliTargetRule:
    return build_bili_target_rule(BiliPushTargetConfig(), config)


def merge_bili_target_rules(
    old_rule: BiliTargetRule,
    new_rule: BiliTargetRule,
) -> BiliTargetRule:
    return BiliTargetRule(
        aliases=old_rule.aliases | new_rule.aliases,
        uids=old_rule.uids | new_rule.uids,
        default_mode=new_rule.default_mode,
        target_mode=new_rule.target_mode,
        modes={**old_rule.modes, **new_rule.modes},
    )


def _resolve_modes(
    modes: dict[str, BiliPushMode],
    config: BiliConfig,
) -> dict[int, BiliPushMode]:
    return {config.accounts[alias].uid: mode for alias, mode in modes.items()}
