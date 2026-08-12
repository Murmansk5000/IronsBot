# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import TYPE_CHECKING, Any, Protocol, TypeVar
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Sequence

    from ironsbot.core.time import ScheduledClockTime

_T = TypeVar("_T")
_MINUTES_PER_HOUR = 60
_MINUTES_PER_DAY = 24 * _MINUTES_PER_HOUR
_SECONDS_PER_MINUTE = 60


class ScheduledJob(Protocol):
    id: str


class Scheduler(Protocol):
    def add_job(
        self,
        func: Any,
        trigger: str,
        **kwargs: Any,
    ) -> ScheduledJob: ...

    def get_jobs(self) -> Sequence[ScheduledJob]: ...

    def remove_job(self, job_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class JobRegistry:
    scheduler: Scheduler
    prefix: str = ""

    def job_id(self, suffix: str) -> str:
        return f"{self.prefix}{suffix}" if self.prefix else suffix

    def add(
        self,
        func: Any,
        trigger: str,
        *,
        job_id: str,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> Any:
        schedule_kwargs = dict(kwargs)
        if trigger == "cron" and "timezone" not in schedule_kwargs:
            timezone = getattr(self.scheduler, "timezone", None)
            if timezone is not None:
                schedule_kwargs["timezone"] = timezone
        return self.scheduler.add_job(
            func,
            trigger,
            id=self.job_id(job_id),
            replace_existing=replace_existing,
            **schedule_kwargs,
        )

    def add_wall_clock_interval(  # noqa: PLR0913 - public scheduling API
        self,
        func: Any,
        *,
        minutes: int,
        offset_minutes: int = 0,
        offset_seconds: int = 0,
        job_id: str,
        replace_existing: bool = True,
        now: datetime | None = None,
        **kwargs: Any,
    ) -> Any:
        """Run a minute interval on stable wall-clock boundaries."""
        trigger, trigger_kwargs = wall_clock_interval_trigger(
            minutes,
            offset_minutes=offset_minutes,
            offset_seconds=offset_seconds,
            schedule_timezone=getattr(self.scheduler, "timezone", None),
            now=now,
        )
        return self.add(
            func,
            trigger,
            job_id=job_id,
            replace_existing=replace_existing,
            **trigger_kwargs,
            **kwargs,
        )

    def add_daily(
        self,
        func: Any,
        *,
        clock_time: ScheduledClockTime,
        job_id: str,
        replace_existing: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Register a recurring daily job from the shared clock-time value."""
        return self.add(
            func,
            "cron",
            job_id=job_id,
            replace_existing=replace_existing,
            **clock_time.cron_kwargs(),
            **kwargs,
        )

    def remove_by_prefix(
        self,
        prefix: str = "",
        *,
        exclude: Collection[str] = (),
    ) -> int:
        scoped_prefix = self.job_id(prefix)
        scoped_exclude = {self.job_id(job_id) for job_id in exclude}
        removed = 0
        for job in self.scheduler.get_jobs():
            job_id = str(job.id)
            if job_id.startswith(scoped_prefix) and job_id not in scoped_exclude:
                self.scheduler.remove_job(job_id)
                removed += 1
        return removed

    def replace_all(
        self,
        register: Callable[[JobRegistry], _T],
        *,
        exclude: Collection[str] = (),
    ) -> _T:
        self.remove_by_prefix(exclude=exclude)
        return register(self)


def wall_clock_interval_trigger(
    minutes: int,
    *,
    offset_minutes: int = 0,
    offset_seconds: int = 0,
    schedule_timezone: str | tzinfo | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    if minutes <= 0:
        msg = "wall-clock interval minutes must be positive"
        raise ValueError(msg)
    if not 0 <= offset_seconds < _SECONDS_PER_MINUTE:
        msg = "wall-clock interval offset seconds must be between 0 and 59"
        raise ValueError(msg)
    if not 0 <= offset_minutes < minutes:
        msg = "wall-clock interval offset minutes must be smaller than interval"
        raise ValueError(msg)

    if minutes <= _MINUTES_PER_HOUR and _MINUTES_PER_HOUR % minutes == 0:
        minute = (
            offset_minutes
            if minutes == _MINUTES_PER_HOUR
            else f"*/{minutes}"
            if offset_minutes == 0
            else f"{offset_minutes}/{minutes}"
        )
        return "cron", {"minute": minute, "second": offset_seconds}

    current = now or datetime.now(timezone.utc)
    local = current.astimezone(_resolve_timezone(schedule_timezone))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    current_seconds = int((local - midnight).total_seconds())
    interval_seconds = minutes * 60
    anchor_seconds = offset_minutes * 60 + offset_seconds
    elapsed_seconds = current_seconds - anchor_seconds
    next_slot = (
        0
        if elapsed_seconds < 0
        else (elapsed_seconds // interval_seconds + 1) * interval_seconds
    )
    return "interval", {
        "minutes": minutes,
        "start_date": midnight + timedelta(seconds=anchor_seconds + next_slot),
    }


def _resolve_timezone(value: str | tzinfo | None) -> tzinfo:
    if isinstance(value, str):
        return ZoneInfo(value)
    if value is not None:
        return value
    return datetime.now().astimezone().tzinfo or timezone.utc
