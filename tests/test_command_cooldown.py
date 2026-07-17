from pytest import MonkeyPatch

from ironsbot.config.models.runtime import CommandCooldownConfig
from ironsbot.shared.messaging import command_cooldown
from ironsbot.shared.messaging.command_cooldown import CommandCooldownService
from tests.helpers.config import stub_app_config

USER_ID = 100


def _set_config(
    monkeypatch: MonkeyPatch,
    *,
    default_seconds: float = 20.0,
    commands: dict[str, float] | None = None,
) -> None:
    monkeypatch.setattr(
        command_cooldown,
        "get_app_config",
        lambda: stub_app_config(
            command_cooldown_config=CommandCooldownConfig(
                default_seconds=default_seconds,
                commands=commands or {},
                cooldown_message="请 {remaining_seconds} 秒后再试。",
                in_progress_message="命令正在处理中。",
            )
        ),
    )
    monkeypatch.setattr(
        command_cooldown,
        "is_superuser",
        lambda _user_id: False,
    )


def test_command_cooldown_tracks_in_progress_and_notifies_once(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch)
    service = CommandCooldownService()

    admitted = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=0,
    )
    first_repeat = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=1,
    )
    second_repeat = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=2,
    )

    assert admitted.allowed
    assert admitted.token is not None
    assert not first_repeat.allowed
    assert first_repeat.feedback == "命令正在处理中。"
    assert not second_repeat.allowed
    assert second_repeat.feedback is None


def test_command_cooldown_starts_after_finish_for_all_outcomes(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch)
    service = CommandCooldownService()
    admitted = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=0,
    )
    assert admitted.token is not None

    service.finish(admitted.token, now=5)

    blocked = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=10,
    )
    available = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=25,
    )

    assert not blocked.allowed
    assert blocked.feedback == "请 15 秒后再试。"
    assert available.allowed


def test_command_cooldown_is_shared_by_user_and_semantic_command(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch)
    service = CommandCooldownService()
    player = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=0,
    )

    assert player.allowed
    assert not service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=1,
    ).allowed
    assert service.admit(
        user_id=USER_ID,
        command_id="seer_team",
        now=1,
    ).allowed
    assert service.admit(
        user_id=USER_ID + 1,
        command_id="seer_player",
        now=1,
    ).allowed


def test_command_cooldown_override_zero_disables_one_command(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, commands={"seer_rank_score": 0})
    service = CommandCooldownService()

    first = service.admit(
        user_id=USER_ID,
        command_id="seer_rank_score",
        now=0,
    )
    second = service.admit(
        user_id=USER_ID,
        command_id="seer_rank_score",
        now=1,
    )

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_command_cooldown_superuser_always_bypasses(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch)
    monkeypatch.setattr(
        command_cooldown,
        "is_superuser",
        lambda _user_id: True,
    )
    service = CommandCooldownService()

    first = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=0,
    )
    second = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=1,
    )

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_command_cooldown_prunes_expired_one_off_keys(
    monkeypatch: MonkeyPatch,
) -> None:
    _set_config(monkeypatch, default_seconds=10.0)
    service = CommandCooldownService()

    first = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=0,
    )
    assert first.token is not None
    service.finish(first.token, now=1)

    service.admit(
        user_id=USER_ID + 1,
        command_id="seer_team",
        now=61,
    )

    assert (USER_ID, "seer_player") not in service._entries
