import asyncio
from dataclasses import dataclass
from pathlib import Path

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

from ironsbot.config import get_app_config
from ironsbot.config.models.bilibili import (
    BiliConfig,
    BiliPushMode,
    BiliPushTargetConfig,
)
from ironsbot.shared.features import (
    group_has_feature,
    is_group_feature_allowed,
    is_private_feature_allowed,
    is_superuser,
    resolve_group_refs,
    resolve_user_refs,
)


def _unique_ints(values: list[int]) -> list[int]:
    return list(dict.fromkeys(item for item in values if item > 0))


@dataclass(frozen=True, slots=True)
class BiliTargetRule:
    uids: frozenset[int]
    mode: BiliPushMode
    uid_modes: dict[int, BiliPushMode]

    def mode_for_uid(self, uid: int) -> BiliPushMode | None:
        if uid not in self.uids:
            return None
        return self.uid_modes.get(uid, self.mode)


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


CONFIGURED_GROUP_RULES: dict[int, BiliTargetRule] | None = None
CONFIGURED_USER_RULES: dict[int, BiliTargetRule] | None = None
PUSH_GROUP_RULES: dict[int, BiliTargetRule] | None = None
PUSH_USER_RULES: dict[int, BiliTargetRule] | None = None
TARGET_GROUP_IDS: list[int] | None = None
TARGET_USER_IDS: list[int] | None = None
MONITORED_UIDS: list[int] | None = None


def get_bili_config() -> BiliConfig:
    return get_app_config().bilibili


def _target_uids(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> frozenset[int]:
    uids = set(target_config.uids)
    uids.update(target_config.uid_modes)
    if not uids:
        uids.update(config.uids)
    return frozenset(uid for uid in uids if uid > 0)


def _resolve_rule(
    target_config: BiliPushTargetConfig,
    config: BiliConfig,
) -> BiliTargetRule:
    return BiliTargetRule(
        uids=_target_uids(target_config, config),
        mode=target_config.mode or config.push.default_mode,
        uid_modes=dict(target_config.uid_modes),
    )


def _merge_rules(old_rule: BiliTargetRule, new_rule: BiliTargetRule) -> BiliTargetRule:
    return BiliTargetRule(
        uids=old_rule.uids | new_rule.uids,
        mode=new_rule.mode,
        uid_modes={**old_rule.uid_modes, **new_rule.uid_modes},
    )


def _resolve_group_rules(config: BiliConfig) -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in config.push.groups.items():
        rule = _resolve_rule(target_config, config)
        for group_id in resolve_group_refs([ref]):
            rules[group_id] = (
                _merge_rules(rules[group_id], rule)
                if group_id in rules
                else rule
            )
    return rules


def _resolve_user_rules(config: BiliConfig) -> dict[int, BiliTargetRule]:
    rules: dict[int, BiliTargetRule] = {}
    for ref, target_config in config.push.users.items():
        rule = _resolve_rule(target_config, config)
        for user_id in resolve_user_refs([ref]):
            rules[user_id] = (
                _merge_rules(rules[user_id], rule)
                if user_id in rules
                else rule
            )
    return rules


def configured_group_rules() -> dict[int, BiliTargetRule]:
    if CONFIGURED_GROUP_RULES is not None:
        return CONFIGURED_GROUP_RULES
    return _resolve_group_rules(get_bili_config())


def configured_user_rules() -> dict[int, BiliTargetRule]:
    if CONFIGURED_USER_RULES is not None:
        return CONFIGURED_USER_RULES
    return _resolve_user_rules(get_bili_config())


def push_group_rules() -> dict[int, BiliTargetRule]:
    if PUSH_GROUP_RULES is not None:
        return PUSH_GROUP_RULES
    return {
        group_id: rule
        for group_id, rule in configured_group_rules().items()
        if group_has_feature(group_id, "bili_push")
    }


def push_user_rules() -> dict[int, BiliTargetRule]:
    if PUSH_USER_RULES is not None:
        return PUSH_USER_RULES
    return {
        user_id: rule
        for user_id, rule in configured_user_rules().items()
        if is_private_feature_allowed(user_id, "bili_push")
    }


def target_group_ids() -> list[int]:
    if TARGET_GROUP_IDS is not None:
        return TARGET_GROUP_IDS
    return _unique_ints(list(push_group_rules()))


def target_user_ids() -> list[int]:
    if TARGET_USER_IDS is not None:
        return TARGET_USER_IDS
    return _unique_ints(list(push_user_rules()))


def monitored_uids() -> list[int]:
    if MONITORED_UIDS is not None:
        return MONITORED_UIDS

    uids = set(get_bili_config().uids)
    for rule in [
        *configured_group_rules().values(),
        *configured_user_rules().values(),
    ]:
        uids.update(rule.uids)
    return _unique_ints(sorted(uids))


def bili_storage_dir() -> Path:
    return get_bili_config().storage.data_dir


def dynamic_history_db_file() -> Path:
    return bili_storage_dir() / "dynamic_history.sqlite"


def cookie_cache_file() -> Path:
    return bili_storage_dir() / "bili_cookie_cache.txt"

AUTH_INVALID_CODES = {-101, -401, -403, 412}
LOGIN_QR_EXPIRE_SECONDS = 180
LOGIN_COOKIE_KEYS = {
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
}

check_lock = asyncio.Lock()


def query_uids_for_group(user_id: int, group_id: int) -> list[int]:
    rule = configured_group_rules().get(group_id)
    if rule is None:
        return []

    if not is_group_feature_allowed(user_id, group_id, "bili_query"):
        return []

    return sorted(rule.uids)


def query_uids_for_private(user_id: int) -> list[int]:
    rule = configured_user_rules().get(user_id)
    if rule is not None:
        if is_private_feature_allowed(user_id, "bili_query"):
            return sorted(rule.uids)
        return []

    if is_superuser(user_id):
        return monitored_uids()

    return []


def query_uids_for_event(event: MessageEvent) -> list[int]:
    if isinstance(event, GroupMessageEvent):
        return query_uids_for_group(event.user_id, event.group_id)

    if isinstance(event, PrivateMessageEvent):
        return query_uids_for_private(event.user_id)

    return []


def push_targets_for_uid(uid: int) -> BiliPushTargets:
    full_group_ids: list[int] = []
    link_group_ids: list[int] = []
    for group_id, rule in push_group_rules().items():
        mode = rule.mode_for_uid(uid)
        if mode == "full":
            full_group_ids.append(group_id)
        elif mode == "link":
            link_group_ids.append(group_id)

    full_user_ids: list[int] = []
    link_user_ids: list[int] = []
    for user_id, rule in push_user_rules().items():
        mode = rule.mode_for_uid(uid)
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
