from ironsbot.core.bilibili import BiliConfig


def bili_accounts(config: BiliConfig) -> dict[str, int]:
    return dict(config.accounts)


def account_uid(account: str, config: BiliConfig) -> int | None:
    return bili_accounts(config).get(account.strip().lower())


def resolve_account_reference(
    reference: str,
    config: BiliConfig,
) -> str | None:
    normalized = reference.strip().lower()
    if not normalized:
        return None
    if normalized in config.accounts:
        return normalized

    folded = reference.strip().casefold()
    matches = [
        account
        for account, nickname in config.account_nicknames.items()
        if nickname.strip().casefold() == folded
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def account_nickname(account: str, config: BiliConfig) -> str | None:
    normalized = account.strip().lower()
    nickname = config.account_nicknames.get(normalized)
    return nickname or None


def account_display_label(
    account: str,
    config: BiliConfig,
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
