import sys
from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "plugins"
    / "startup_notice"
    / "service.py"
)
_SPEC = spec_from_file_location("startup_notice_service_for_test", _SERVICE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SERVICE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SERVICE
_SPEC.loader.exec_module(_SERVICE)
StartupNoticeService = _SERVICE.StartupNoticeService


@dataclass
class Config:
    enabled: bool = True


def test_startup_notice_service_respects_enabled_and_busy_state() -> None:
    service = StartupNoticeService()

    assert not service.should_send(Config(enabled=False))
    assert service.should_send(Config())

    service.begin_send()
    assert not service.should_send(Config())


def test_startup_notice_service_resolves_targets() -> None:
    service = StartupNoticeService(
        superuser_loader=lambda: {3, 1},
        feature_group_loader=lambda feature: [9] if feature == "admin_notice" else [],
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

    assert not service.state.sent
    assert not service.state.sending


def test_startup_notice_service_marks_successful_send() -> None:
    service = StartupNoticeService()

    service.begin_send()
    service.mark_result([123])
    service.finish_send()

    assert service.state.sent
