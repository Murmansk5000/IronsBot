import asyncio
from pathlib import Path

import pytest

from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.seer import render_crash_report
from tests.helpers.runtime import build_test_runtime


def test_render_crash_marker_clears_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "marker.json"
    monkeypatch.setattr(render_crash_report, "MARKER_PATH", marker_path)

    with render_crash_report.render_crash_marker(
        operation="pet_info_render",
        pet_id=3570,
        pet_name="星诺",
        resource_id=3570,
    ):
        assert marker_path.exists()

    assert not marker_path.exists()


def test_report_previous_render_crash_notifies_superusers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "marker.json"
    marker_path.write_text(
        '{"started_at":"2026-06-22 12:55:20",'
        '"operation":"pet_info_render",'
        '"pet_id":4894,'
        '"pet_name":"安瑟伦",'
        '"resource_id":4894}',
        encoding="utf-8",
    )
    notices: list[tuple[str, str]] = []

    async def fake_notify(
        _service: AdminNoticeService,
        message: str,
        **_kwargs: object,
    ) -> None:
        notices.append(("render_crash_notice", message))

    monkeypatch.setattr(render_crash_report, "MARKER_PATH", marker_path)
    monkeypatch.setattr(AdminNoticeService, "send", fake_notify)
    reporter = render_crash_report.RenderCrashReporter(
        build_test_runtime().admin_notices
    )
    reporter.capture_previous()

    asyncio.run(reporter.report_previous(object()))

    assert not marker_path.exists()
    assert len(notices) == 1
    key, message = notices[0]
    assert key == "render_crash_notice"
    assert "安瑟伦" in message
    assert "最近日志" not in message
    assert "Chromium" not in message


def test_current_render_after_startup_is_not_reported_as_previous_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "marker.json"
    notices: list[str] = []

    async def fake_notify(
        _service: AdminNoticeService,
        message: str,
        **_kwargs: object,
    ) -> None:
        notices.append(message)

    monkeypatch.setattr(render_crash_report, "MARKER_PATH", marker_path)
    monkeypatch.setattr(AdminNoticeService, "send", fake_notify)
    reporter = render_crash_report.RenderCrashReporter(
        build_test_runtime().admin_notices
    )
    reporter.capture_previous()

    with render_crash_report.render_crash_marker(
        operation="pet_info_render",
        pet_id=4946,
        pet_name="雷伊",
        resource_id=4946,
    ):
        asyncio.run(reporter.report_previous(object()))
        assert marker_path.exists()

    assert notices == []
    assert not marker_path.exists()
