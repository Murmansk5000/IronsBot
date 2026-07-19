from ironsbot.services.operations.startup import StartupNoticeService
from tests.helpers.runtime import build_test_runtime


def _service() -> StartupNoticeService:
    return StartupNoticeService(build_test_runtime().admin_notices)


def test_startup_notice_service_respects_enabled_and_busy_state() -> None:
    service = _service()

    assert not service.should_send(enabled=False)
    assert service.should_send(enabled=True)

    service.begin_send()
    assert not service.should_send(enabled=True)


def test_startup_notice_service_resets_sending_after_failed_send() -> None:
    service = _service()

    service.begin_send()
    service.mark_result([])
    service.finish_send()

    assert not service.sent
    assert not service.sending


def test_startup_notice_service_marks_successful_send() -> None:
    service = _service()

    service.begin_send()
    service.mark_result([123])
    service.finish_send()

    assert service.sent
    assert not service.sending
