# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from enum import IntEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .docker_formatting import format_docker_update_reply
from .docker_models import DockerUpdateResult

if TYPE_CHECKING:
    from ironsbot.config.models.operations import DockerUpdateConfig

DEFAULT_DOCKER_STARTUP_PREFLIGHT_PATH = Path(
    "data/operations/docker_startup_preflight.json"
)
logger = logging.getLogger(__name__)


class DockerStartupPreflightRecordError(ValueError):
    pass


class DockerStartupPreflightAction(IntEnum):
    CONTINUE = 0
    WAIT_FOR_WATCHTOWER = 75


class DockerUpdateRunner(Protocol):
    async def run_update(self) -> tuple[str, DockerUpdateResult]: ...


@dataclass(frozen=True, slots=True)
class DockerStartupPreflightRecord:
    container_name: str
    image: str
    result: DockerUpdateResult
    source_instance_id: str = ""


class DockerStartupPreflightStore:
    def __init__(self, path: Path = DEFAULT_DOCKER_STARTUP_PREFLIGHT_PATH) -> None:
        self._path = path

    def clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "could not clear docker startup preflight record: %s",
                self._path,
                exc_info=True,
            )

    def save(self, record: DockerStartupPreflightRecord) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(f"{self._path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(
                {
                    "container_name": record.container_name,
                    "image": record.image,
                    "result": asdict(record.result),
                    "source_instance_id": record.source_instance_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(self._path)

    def take(self) -> DockerStartupPreflightRecord | None:
        try:
            return self.read()
        finally:
            self.clear()

    def read(self) -> DockerStartupPreflightRecord | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return _record_from_payload(payload)
        except FileNotFoundError:
            return None
        except (OSError, TypeError, ValueError):
            logger.warning(
                "could not read docker startup preflight record: %s",
                self._path,
                exc_info=True,
            )
            return None


def _record_from_payload(payload: object) -> DockerStartupPreflightRecord:
    if not isinstance(payload, dict):
        raise DockerStartupPreflightRecordError
    container_name = payload.get("container_name")
    image = payload.get("image")
    result = payload.get("result")
    source_instance_id = payload.get("source_instance_id", "")
    if not isinstance(container_name, str) or not isinstance(image, str):
        raise DockerStartupPreflightRecordError
    if not isinstance(result, dict):
        raise DockerStartupPreflightRecordError
    if not isinstance(source_instance_id, str):
        raise DockerStartupPreflightRecordError
    return DockerStartupPreflightRecord(
        container_name=container_name,
        image=image,
        result=DockerUpdateResult(**result),
        source_instance_id=source_instance_id,
    )


class DockerStartupPreflightService:
    def __init__(
        self,
        config: DockerUpdateConfig,
        update_runner: DockerUpdateRunner,
        store: DockerStartupPreflightStore,
        *,
        instance_id: str | None = None,
    ) -> None:
        self._config = config
        self._update_runner = update_runner
        self._store = store
        self._instance_id = (
            instance_id if instance_id is not None else os.environ.get("HOSTNAME", "")
        )

    async def run(self) -> DockerStartupPreflightAction:
        if not self._config.check_on_startup:
            self._store.clear()
            return DockerStartupPreflightAction.CONTINUE
        if self._has_completed_handoff():
            return DockerStartupPreflightAction.CONTINUE

        try:
            container_name, result = await self._update_runner.run_update()
        except Exception as error:
            logger.exception("docker startup preflight failed")
            container_name = str(self._config.container_name)
            result = DockerUpdateResult(ok=False, message=str(error))

        try:
            self._store.save(
                DockerStartupPreflightRecord(
                    container_name=container_name,
                    image=str(self._config.image),
                    result=result,
                    source_instance_id=self._instance_id,
                )
            )
        except OSError:
            logger.warning(
                "could not persist docker startup preflight result",
                exc_info=True,
            )

        if result.ok and not result.up_to_date and result.updater_container_id:
            logger.warning(
                "docker startup preflight launched Watchtower update: container=%s",
                container_name,
            )
            return DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
        return DockerStartupPreflightAction.CONTINUE

    def _has_completed_handoff(self) -> bool:
        record = self._store.read()
        if record is None:
            return False
        return (
            record.image == str(self._config.image)
            and bool(record.source_instance_id)
            and bool(self._instance_id)
            and record.source_instance_id != self._instance_id
            and record.result.ok
            and not record.result.up_to_date
            and bool(record.result.updater_container_id)
        )


def consume_docker_startup_preflight_notice(
    store: DockerStartupPreflightStore | None = None,
) -> str | None:
    record = (store or DockerStartupPreflightStore()).take()
    if record is None:
        return None
    return format_docker_update_reply(
        container_name=record.container_name,
        image=record.image,
        result=record.result,
    )
