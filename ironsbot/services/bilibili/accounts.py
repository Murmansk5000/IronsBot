from ironsbot.config.loader import get_app_config
from ironsbot.config.models.bilibili import BiliConfig


def get_bili_config() -> BiliConfig:
    return get_app_config().bilibili


def bili_accounts(config: BiliConfig | None = None) -> dict[str, int]:
    return dict((config or get_bili_config()).accounts)


def account_uid(account: str, config: BiliConfig | None = None) -> int | None:
    return bili_accounts(config).get(account.strip().lower())


def resolve_account_reference(
    reference: str,
    config: BiliConfig | None = None,
) -> str | None:
    bili_config = config or get_bili_config()
    normalized = reference.strip().lower()
    if not normalized:
        return None
    if normalized in bili_config.accounts:
        return normalized

    folded = reference.strip().casefold()
    matches = [
        account
        for account, nickname in bili_config.account_nicknames.items()
        if nickname.strip().casefold() == folded
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def account_for_uid(uid: int, config: BiliConfig | None = None) -> str | None:
    for account, account_uid_value in bili_accounts(config).items():
        if account_uid_value == int(uid):
            return account
    return None


def account_nickname(account: str, config: BiliConfig | None = None) -> str | None:
    normalized = account.strip().lower()
    nickname = (config or get_bili_config()).account_nicknames.get(normalized)
    return nickname or None


def account_display_label(
    account: str,
    config: BiliConfig | None = None,
    *,
    uid: int | None = None,
) -> str:
    normalized = account.strip().lower()
    resolved_uid = uid if uid is not None else account_uid(normalized, config)
    nickname = account_nickname(normalized, config)
    if resolved_uid is None:
        return nickname or normalized
    if nickname:
        return f"{nickname}\uff08{int(resolved_uid)}\uff09"
    return f"{normalized}\uff08{int(resolved_uid)}\uff09"


def account_label(uid: int, config: BiliConfig | None = None) -> str:
    account = account_for_uid(uid, config)
    return account_display_label(account, config) if account else str(int(uid))
