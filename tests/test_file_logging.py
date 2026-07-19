from pathlib import Path

from ironsbot.app.file_logging import FileLogging
from ironsbot.config.models.settings import LoggingConfig, PathsConfig


def test_file_logging_registers_file_sink(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ironsbot.log"
    resource = FileLogging.create(
        LoggingConfig(file_enabled=True),
        PathsConfig(log_file=log_path),
    )

    try:
        assert len(resource.sink_ids) == 1
        assert log_path.parent.exists()
    finally:
        resource.close()

    assert resource.sink_ids == []


def test_file_logging_registers_error_file_sink(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ironsbot.log"
    error_log_path = tmp_path / "logs" / "ironsbot.error.log"
    resource = FileLogging.create(
        LoggingConfig(file_enabled=True, error_file_enabled=True),
        PathsConfig(log_file=log_path, error_log_file=error_log_path),
    )

    try:
        assert len(resource.sink_ids) == len((log_path, error_log_path))
        assert log_path.parent.exists()
        assert error_log_path.parent.exists()
    finally:
        resource.close()
