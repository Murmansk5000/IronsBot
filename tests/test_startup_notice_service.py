from ironsbot.services.startup_notice import StartupNoticeService
from ironsbot.shared.messaging.admin_notice import AdminNoticeTargets


def test_startup_notice_service_respects_enabled_and_busy_state() -> None:
    service = StartupNoticeService()

    assert not service.should_send(enabled=False)
    assert service.should_send(enabled=True)

    service.begin_send()
    assert not service.should_send(enabled=True)


def test_startup_notice_service_resolves_targets() -> None:
    service = StartupNoticeService(
        target_loader=lambda: AdminNoticeTargets(
            private_user_ids=[1, 3],
            group_ids=[9],
        ),
    )

    targets = service.get_targets()

    assert targets.private_user_ids == [1, 3]
    assert targets.group_ids == [9]
    assert not targets.is_empty


def test_startup_notice_service_resets_sending_after_failed_send() -> None:
    service = StartupNoticeService()

    service.begin_send()
    service.mark_result([])
    service.finish_send()

    assert not service.sent
    assert not service.sending


def test_startup_notice_service_marks_successful_send() -> None:
    service = StartupNoticeService()

    service.begin_send()
    service.mark_result([123])
    service.finish_send()

    assert service.sent
    assert not service.sending
