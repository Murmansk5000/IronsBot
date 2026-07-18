from dataclasses import dataclass, field

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.config.models.bilibili import (
    BiliConfig,
    BiliPushMode,
    BiliPushTargetConfig,
)
from ironsbot.services.bilibili.accounts import account_uid, get_bili_config
from ironsbot.services.bilibili.preferences import (
    bili_push_subscription_key,
    bili_push_subscription_label,
)
from ironsbot.services.bilibili.storage import push_preference_store
from ironsbot.shared.features import FeatureService
from ironsbot.shared.messaging.push_subscription_models import (
    PushSubscriptionOption,
    PushTargetType,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushUnsubscribeStore,
)


def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(item for item in values if item > 0))


@dataclass(frozen=True, slots=True)
class BiliTargetRule:
    accounts: frozenset[str]
    uids: frozenset[int]
    uid_accounts: dict[int, str]
    mode: BiliPushMode
    modes: dict[str, BiliPushMode]
    account_nicknames: dict[str, str] = field(default_factory=dict)

    def mode_for_uid(self, uid: int) -> BiliPushMode | None:
        if uid not in self.uids:
            return None
        account = self.account_for_uid(uid)
        if account is None:
            return self.mode
        return self.modes.get(account, self.mode)

    def account_for_uid(self, uid: int) -> str | None:
        return self.uid_accounts.get(uid)

    def label_for_uid(self, uid: int) -> str:
        account = self.account_for_uid(uid)
        if account is None:
            return str(int(uid))
        nickname = self.account_nicknames.get(account)
        if nickname:
            return f"{nickname}\uff08{int(uid)}\uff09"
        return f"{account}\uff08{int(uid)}\uff09"


@dataclass(frozen=True, slots=True)
class BiliPushTargets:
    full_group_ids: list[int]
    link_group_ids: list[int]
    full_user_ids: list[int]
    link_user_ids: list[int]

    @property
    def has_targets(self) -> bool:
        return any(
            (
                self.full_group_ids,
                self.link_group_ids,
                self.full_user_ids,
                self.link_user_ids,
            )
        )


def _target_accounts(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> frozenset[str]:
    return frozenset(
        [
            *config.push.accounts,
            *target_config.accounts,
        ]
    )


def _resolve_rule(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> BiliTargetRule:
    accounts = _target_accounts(target_config, config)
    account_to_uid = {
        account: config.accounts[account]
        for account in accounts
    }
    uid_accounts = {
        uid: account
        for account, uid in account_to_uid.items()
        if uid > 0
    }
    account_nicknames = {
        account: nickname
        for account in accounts
        if (nickname := config.account_nicknames.get(account))
    }
    return BiliTargetRule(
        accounts=accounts,
        uids=frozenset(uid for uid in account_to_uid.values() if uid > 0),
        uid_accounts=uid_accounts,
        account_nicknames=account_nicknames,
        mode=target_config.mode or config.push.mode,
        modes={**config.push.modes, **target_config.modes},
    )


def _default_rule(config: BiliConfig) -> BiliTargetRule:
    return _resolve_rule(BiliPushTargetConfig(), config)


def _merge_rules(old_rule: BiliTargetRule, new_rule: BiliTargetRule) -> BiliTargetRule:
    return BiliTargetRule(
        accounts=old_rule.accounts | new_rule.accounts,
        uids=old_rule.uids | new_rule.uids,
        uid_accounts={**old_rule.uid_accounts, **new_rule.uid_accounts},
        account_nicknames={
            **old_rule.account_nicknames,
            **new_rule.account_nicknames,
        },
        mode=new_rule.mode,
        modes={**old_rule.modes, **new_rule.modes},
    )


def _resolve_group_rules(
    features: FeatureService,
    config: BiliConfig,
) -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in config.push.groups.items():
        rule = _resolve_rule(target_config, config)
        for group_id in features.resolve_group_refs([ref]):
            rules[group_id] = (
                _merge_rules(rules[group_id], rule)
                if group_id in rules
                else rule
            )
    return rules


def _resolve_user_rules(
    features: FeatureService,
    config: BiliConfig,
) -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in config.push.users.items():
        rule = _resolve_rule(target_config, config)
        for user_id in features.resolve_user_refs([ref]):
            rules[user_id] = (
                _merge_rules(rules[user_id], rule)
                if user_id in rules
                else rule
            )
    return rules


def configured_group_rules(
    features: FeatureService,
) -> dict[int, BiliTargetRule]:
    return _resolve_group_rules(features, get_bili_config())


def configured_user_rules(
    features: FeatureService,
) -> dict[int, BiliTargetRule]:
    return _resolve_user_rules(features, get_bili_config())


def push_group_rules(features: FeatureService) -> dict[int, BiliTargetRule]:
    config = get_bili_config()
    default_rule = _default_rule(config)
    configured_rules = configured_group_rules(features)
    return {
        group_id: configured_rules.get(group_id, default_rule)
        for group_id in features.groups_for_feature("bili_push")
    }


def push_user_rules(features: FeatureService) -> dict[int, BiliTargetRule]:
    config = get_bili_config()
    default_rule = _default_rule(config)
    configured_rules = configured_user_rules(features)
    return {
        user_id: configured_rules.get(user_id, default_rule)
        for user_id in features.users_for_feature("bili_push")
    }


def monitored_uids(features: FeatureService) -> list[int]:
    config = get_bili_config()
    uids = set(_default_rule(config).uids)
    for rule in [
        *configured_group_rules(features).values(),
        *configured_user_rules(features).values(),
    ]:
        uids.update(rule.uids)
    return _unique_ints(sorted(uids))


def query_uids_for_group(
    features: FeatureService,
    user_id: int,
    group_id: int,
) -> list[int]:
    if not features.is_group_feature_allowed(user_id, group_id, "bili_query"):
        return []

    rule = configured_group_rules(features).get(group_id)
    if rule is None:
        rule = _default_rule(get_bili_config())
    return sorted(rule.uids)


def query_uids_for_private(
    features: FeatureService,
    user_id: int,
) -> list[int]:
    rule = configured_user_rules(features).get(user_id)
    if rule is not None:
        if features.is_private_feature_allowed(user_id, "bili_query"):
            return sorted(rule.uids)
        return []

    if features.is_superuser(user_id):
        return monitored_uids(features)

    return []


def query_uids_for_event(
    features: FeatureService,
    event: MessageEvent,
) -> list[int]:
    if isinstance(event, GroupMessageEvent):
        return query_uids_for_group(features, event.user_id, event.group_id)

    if isinstance(event, PrivateMessageEvent):
        return query_uids_for_private(features, event.user_id)

    return []


def _runtime_mode_for_target(
    target_type: PushTargetType,
    target_id: int,
    uid: int,
) -> BiliPushMode | None:
    return push_preference_store().get_mode(target_type, target_id, uid)


def mode_for_target_uid(
    features: FeatureService,
    target_type: PushTargetType,
    target_id: int,
    uid: int,
) -> BiliPushMode | None:
    rules = (
        push_group_rules(features)
        if target_type == "group"
        else push_user_rules(features)
    )
    rule = rules.get(target_id)
    if rule is None or uid not in rule.uids:
        return None
    return (
        _runtime_mode_for_target(target_type, target_id, uid)
        or rule.mode_for_uid(uid)
        or rule.mode
    )


def mode_for_target_account(
    features: FeatureService,
    target_type: PushTargetType,
    target_id: int,
    account: str,
) -> BiliPushMode | None:
    uid = account_uid(account)
    if uid is None:
        return None
    return mode_for_target_uid(features, target_type, target_id, uid)


def target_rule(
    features: FeatureService,
    target_type: PushTargetType,
    target_id: int,
) -> BiliTargetRule | None:
    rules = (
        push_group_rules(features)
        if target_type == "group"
        else push_user_rules(features)
    )
    return rules.get(target_id)


def bili_push_subscription_options(
    *,
    target_type: PushTargetType,
    target_id: int,
    store: PushUnsubscribeStore,
    features: FeatureService,
) -> list[PushSubscriptionOption]:
    rules = (
        push_group_rules(features)
        if target_type == "group"
        else push_user_rules(features)
    )
    rule = rules.get(target_id)
    if rule is None:
        return []

    unsubscribed = store.target_unsubscribed_keys(target_type, target_id)
    options: list[PushSubscriptionOption] = []
    for uid in sorted(rule.uids):
        key = bili_push_subscription_key(uid)
        is_unsubscribed = key in unsubscribed
        options.append(
            PushSubscriptionOption(
                key=key,
                label=bili_push_subscription_label(uid, rule.label_for_uid(uid)),
                feature="bili_push",
                unsubscribed=is_unsubscribed,
            )
        )
    return options


def push_targets_for_uid(
    features: FeatureService,
    uid: int,
) -> BiliPushTargets:
    full_group_ids: list[int] = []
    link_group_ids: list[int] = []
    for group_id in push_group_rules(features):
        mode = mode_for_target_uid(features, "group", group_id, uid)
        if mode == "full":
            full_group_ids.append(group_id)
        elif mode == "link":
            link_group_ids.append(group_id)

    full_user_ids: list[int] = []
    link_user_ids: list[int] = []
    for user_id in push_user_rules(features):
        mode = mode_for_target_uid(features, "private", user_id, uid)
        if mode == "full":
            full_user_ids.append(user_id)
        elif mode == "link":
            link_user_ids.append(user_id)

    return BiliPushTargets(
        full_group_ids=_unique_ints(full_group_ids),
        link_group_ids=_unique_ints(link_group_ids),
        full_user_ids=_unique_ints(full_user_ids),
        link_user_ids=_unique_ints(link_user_ids),
    )
