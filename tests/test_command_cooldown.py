from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
)
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from tests.helpers.runtime import build_test_runtime

USER_ID = 100


def _windows(*entries: tuple[float, int]) -> list[CommandCooldownWindowConfig]:
    return [
        CommandCooldownWindowConfig(
            window_seconds=window_seconds,
            max_requests=max_requests,
        )
        for window_seconds, max_requests in entries
    ]


def _service(
    *,
    windows: list[CommandCooldownWindowConfig] | None = None,
    commands: dict[str, list[CommandCooldownWindowConfig]] | None = None,
    superuser: bool = False,
) -> CommandCooldownService:
    config = CommandCooldownConfig(
        enabled=True,
        windows=windows or _windows((60.0, 3), (300.0, 5)),
        commands=commands or {},
        cooldown_message="Try again in {remaining_seconds} seconds.",
        in_progress_message="Command is in progress.",
    )
    return build_test_runtime(
        cooldown_config=config,
        superuser_ids=(USER_ID,) if superuser else (),
    ).cooldown


def test_command_cooldown_is_disabled_by_default() -> None:
    service = build_test_runtime().cooldown

    first = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    second = service.admit(user_id=USER_ID, command_id="seer_player", now=1)

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def _complete(
    service: CommandCooldownService,
    *,
    command_id: str,
    started_at: float,
    finished_at: float | None = None,
) -> None:
    admitted = service.admit(
        user_id=USER_ID,
        command_id=command_id,
        now=started_at,
    )
    assert admitted.allowed
    assert admitted.token is not None
    completed_at = started_at if finished_at is None else finished_at
    service.finish(admitted.token, now=completed_at)


def test_command_cooldown_tracks_in_progress_and_notifies_once() -> None:
    service = _service()
    admitted = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    first_repeat = service.admit(user_id=USER_ID, command_id="seer_player", now=1)
    second_repeat = service.admit(user_id=USER_ID, command_id="seer_player", now=2)

    assert admitted.allowed
    assert admitted.token is not None
    assert not first_repeat.allowed
    assert first_repeat.feedback == "Command is in progress."
    assert not second_repeat.allowed
    assert second_repeat.feedback is None


def test_command_cooldown_release_does_not_consume_a_window_slot() -> None:
    service = _service(windows=_windows((60.0, 1)))
    admitted = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    assert admitted.token is not None

    service.release(admitted.token)

    retry = service.admit(user_id=USER_ID, command_id="seer_player", now=1)
    assert retry.allowed


def test_command_cooldown_enforces_multiple_sliding_windows() -> None:
    service = _service()

    for timestamp in (0, 1, 2):
        _complete(service, command_id="seer_player", started_at=timestamp)

    minute_limited = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=3,
    )
    assert not minute_limited.allowed
    assert minute_limited.feedback == "Try again in 57 seconds."

    _complete(service, command_id="seer_player", started_at=60)
    _complete(service, command_id="seer_player", started_at=61)
    five_minute_limited = service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=62,
    )
    assert not five_minute_limited.allowed
    assert five_minute_limited.feedback == "Try again in 238 seconds."


def test_player_query_commands_have_independent_windows() -> None:
    service = _service()

    for timestamp in (0, 1, 2):
        _complete(service, command_id="seer_player", started_at=timestamp)

    assert not service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=3,
    ).allowed
    for command_id in (
        "seer_player_collection",
        "seer_player_peak",
        "seer_player_autocard",
        "player_lineup_private",
    ):
        assert service.admit(
            user_id=USER_ID,
            command_id=command_id,
            now=3,
        ).allowed


def test_command_cooldown_override_can_disable_one_command() -> None:
    service = _service(commands={"seer_rank_score": []})
    first = service.admit(user_id=USER_ID, command_id="seer_rank_score", now=0)
    second = service.admit(user_id=USER_ID, command_id="seer_rank_score", now=1)

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_command_cooldown_override_replaces_default_windows() -> None:
    service = _service(
        commands={"seer_player": _windows((10.0, 1))},
    )
    _complete(service, command_id="seer_player", started_at=0)

    blocked = service.admit(user_id=USER_ID, command_id="seer_player", now=1)
    assert not blocked.allowed
    assert blocked.feedback == "Try again in 9 seconds."
    assert service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=10,
    ).allowed


def test_command_cooldown_superuser_always_bypasses() -> None:
    service = _service(superuser=True)
    first = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    second = service.admit(user_id=USER_ID, command_id="seer_player", now=1)

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_command_cooldown_prunes_expired_windows() -> None:
    service = _service(windows=_windows((10.0, 1)))
    _complete(service, command_id="seer_player", started_at=0)

    service.admit(user_id=USER_ID + 1, command_id="seer_team", now=61)

    assert (USER_ID, "seer_player") not in service._entries
