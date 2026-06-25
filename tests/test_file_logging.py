from pathlib import Path

from nonebot.log import logger

from ironsbot.app import file_logging
from ironsbot.config.models.runtime import LoggingConfig


def _remove_sink(sink_id: int | None) -> None:
    if sink_id is not None:
        logger.remove(sink_id)


def test_configure_file_logging_registers_file_sink(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ironsbot.log"
    config = LoggingConfig(file_enabled=True, file_path=str(log_path))
    previous_sink_id = file_logging._FILE_LOG_SINK_ID
    previous_error_sink_id = file_logging._ERROR_FILE_LOG_SINK_ID
    file_logging._FILE_LOG_SINK_ID = None
    file_logging._ERROR_FILE_LOG_SINK_ID = None
    sink_id = None

    try:
        sink_id = file_logging.configure_file_logging(config)

        assert sink_id is not None
        assert log_path.parent.exists()
        assert file_logging._ERROR_FILE_LOG_SINK_ID is None
    finally:
        _remove_sink(sink_id)
        file_logging._FILE_LOG_SINK_ID = previous_sink_id
        file_logging._ERROR_FILE_LOG_SINK_ID = previous_error_sink_id


def test_configure_file_logging_registers_error_file_sink(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "ironsbot.log"
    error_log_path = tmp_path / "logs" / "ironsbot.error.log"
    config = LoggingConfig(
        file_enabled=True,
        file_path=str(log_path),
        error_file_enabled=True,
        error_file_path=str(error_log_path),
    )
    previous_sink_id = file_logging._FILE_LOG_SINK_ID
    previous_error_sink_id = file_logging._ERROR_FILE_LOG_SINK_ID
    file_logging._FILE_LOG_SINK_ID = None
    file_logging._ERROR_FILE_LOG_SINK_ID = None
    sink_id = None
    error_sink_id = None

    try:
        sink_id = file_logging.configure_file_logging(config)
        error_sink_id = file_logging._ERROR_FILE_LOG_SINK_ID

        assert sink_id is not None
        assert error_sink_id is not None
        assert log_path.parent.exists()
        assert error_log_path.parent.exists()
    finally:
        _remove_sink(error_sink_id)
        _remove_sink(sink_id)
        file_logging._FILE_LOG_SINK_ID = previous_sink_id
        file_logging._ERROR_FILE_LOG_SINK_ID = previous_error_sink_id
