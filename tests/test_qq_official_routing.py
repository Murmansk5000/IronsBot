from pathlib import Path

from ironsbot.app.common_composition import _build_qq_official_ingress_routing
from ironsbot.config.loader import load_settings
from ironsbot.core.qq_official_routing import QQOfficialIngressRouting


def test_default_account_owns_private_and_unassigned_groups() -> None:
    routing = QQOfficialIngressRouting(
        "public-app",
        {},
        use_default_for_unconfigured_groups=True,
    )

    assert routing.allows(
        account_id="public-app",
        conversation_kind="private",
        conversation_id="user",
    )
    assert routing.allows(
        account_id="local-app",
        conversation_kind="private",
        conversation_id="user",
    )
    assert routing.allows(
        account_id="public-app",
        conversation_kind="group",
        conversation_id="unknown-group",
    )
    assert not routing.allows(
        account_id="local-app",
        conversation_kind="group",
        conversation_id="unknown-group",
    )


def test_addressed_account_cannot_bootstrap_an_unassigned_group() -> None:
    routing = QQOfficialIngressRouting("public-app", {})

    assert not routing.allows(
        account_id="local-app",
        conversation_kind="group",
        conversation_id="unknown-group",
        explicitly_addressed=True,
    )
    assert routing.allows(
        account_id="local-app",
        conversation_kind="private",
        conversation_id="unknown-user",
        explicitly_addressed=True,
    )


def test_unconfigured_group_is_ignored_by_default() -> None:
    routing = QQOfficialIngressRouting("public-app", {})

    assert not routing.allows(
        account_id="public-app",
        conversation_kind="group",
        conversation_id="unknown-group",
    )
    assert not routing.allows(
        account_id="local-app",
        conversation_kind="group",
        conversation_id="unknown-group",
        explicitly_addressed=True,
    )


def test_explicit_group_route_overrides_default_for_every_known_endpoint() -> None:
    routing = QQOfficialIngressRouting(
        "public-app",
        {"686376929": "local-app"},
    )
    routing.register_group_endpoint(
        account_id="local-app",
        official_group_openid="local-openid",
        onebot_group_id="686376929",
    )
    routing.register_group_endpoint(
        account_id="public-app",
        official_group_openid="public-openid",
        onebot_group_id="686376929",
    )

    assert routing.allows(
        account_id="local-app",
        conversation_kind="group",
        conversation_id="local-openid",
    )
    assert not routing.allows(
        account_id="public-app",
        conversation_kind="group",
        conversation_id="public-openid",
    )


def test_single_configured_group_endpoint_owns_group_without_duplicate_route(
    tmp_path: Path,
) -> None:
    config = tmp_path / "ironsbot.toml"
    config.write_text(
        """
[bot.qq_official]
default_account = "public_bot"

[bot.qq_official.accounts.public_bot]
app_id = "10001"

[bot.qq_official.accounts.local_bot]
app_id = "10002"

[identities.groups.admin]
qq = 686376929

[identities.groups.admin.official]
local_bot = "local-group-openid"
""".strip(),
        encoding="utf-8",
    )
    settings = load_settings(
        config,
        env={
            "APP_SECRET_10001": "public-secret",
            "APP_SECRET_10002": "local-secret",
        },
    )

    routing = _build_qq_official_ingress_routing(settings)

    assert routing.allows(
        account_id="10002",
        conversation_kind="group",
        conversation_id="local-group-openid",
    )
