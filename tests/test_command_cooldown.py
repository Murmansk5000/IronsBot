from ironsbot.config.models.messaging import CommandCooldownConfig
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from tests.helpers.runtime import build_test_runtime

USER_ID = 100


def _service(
    *,
    default_seconds: float = 20.0,
    commands: dict[str, float] | None = None,
    superuser: bool = False,
) -> CommandCooldownService:
    config = CommandCooldownConfig(
        default_seconds=default_seconds,
        commands=commands or {},
        cooldown_message="请 {remaining_seconds} 秒后再试。",
        in_progress_message="命令正在处理中。",
    )
    return build_test_runtime(
        cooldown_config=config,
        superuser_ids=(USER_ID,) if superuser else (),
    ).cooldown


def test_command_cooldown_tracks_in_progress_and_notifies_once() -> None:
    service = _service()
    admitted = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    first_repeat = service.admit(user_id=USER_ID, command_id="seer_player", now=1)
    second_repeat = service.admit(user_id=USER_ID, command_id="seer_player", now=2)

    assert admitted.allowed
    assert admitted.token is not None
    assert not first_repeat.allowed
    assert first_repeat.feedback == "命令正在处理中。"
    assert not second_repeat.allowed
    assert second_repeat.feedback is None


def test_command_cooldown_starts_after_finish_for_all_outcomes() -> None:
    service = _service()
    admitted = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    assert admitted.token is not None

    service.finish(admitted.token, now=5)
    blocked = service.admit(user_id=USER_ID, command_id="seer_player", now=10)
    available = service.admit(user_id=USER_ID, command_id="seer_player", now=25)

    assert not blocked.allowed
    assert blocked.feedback == "请 15 秒后再试。"
    assert available.allowed


def test_command_cooldown_is_shared_by_user_and_semantic_command() -> None:
    service = _service()
    assert service.admit(user_id=USER_ID, command_id="seer_player", now=0).allowed
    assert not service.admit(
        user_id=USER_ID,
        command_id="seer_player",
        now=1,
    ).allowed
    assert service.admit(user_id=USER_ID, command_id="seer_team", now=1).allowed
    assert service.admit(
        user_id=USER_ID + 1,
        command_id="seer_player",
        now=1,
    ).allowed


def test_command_cooldown_override_zero_disables_one_command() -> None:
    service = _service(commands={"seer_rank_score": 0})
    first = service.admit(user_id=USER_ID, command_id="seer_rank_score", now=0)
    second = service.admit(user_id=USER_ID, command_id="seer_rank_score", now=1)

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_command_cooldown_superuser_always_bypasses() -> None:
    service = _service(superuser=True)
    first = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    second = service.admit(user_id=USER_ID, command_id="seer_player", now=1)

    assert first.allowed and first.token is None
    assert second.allowed and second.token is None


def test_command_cooldown_prunes_expired_one_off_keys() -> None:
    service = _service(default_seconds=10.0)
    first = service.admit(user_id=USER_ID, command_id="seer_player", now=0)
    assert first.token is not None
    service.finish(first.token, now=1)

    service.admit(user_id=USER_ID + 1, command_id="seer_team", now=61)

    assert (USER_ID, "seer_player") not in service._entries
