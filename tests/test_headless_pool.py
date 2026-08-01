import asyncio
from dataclasses import dataclass
from typing import cast

from ironsbot.services.operations.headless_pool import HeadlessPool, HeadlessWorker

PRIMARY_WORKER = "primary"
SECOND_WORKER = "rank_a"


@dataclass
class _Service:
    worker_id: int
    configured: bool = True
    connected: bool = True

    @property
    def user_id_text(self) -> str:
        return str(self.worker_id)

    @property
    def reconnect_times(self) -> list[str]:
        return ["00:05"]

    def get_game(self) -> int:
        if not self.connected:
            from ironsbot.services.operations.headless_errors import DisconnectedError

            raise DisconnectedError("offline")
        return self.worker_id


def test_pool_round_robins_healthy_workers() -> None:
    pool = HeadlessPool(
        (
            HeadlessWorker(key=PRIMARY_WORKER, service=_Service(1)),  # type: ignore[arg-type]
            HeadlessWorker(
                key=SECOND_WORKER,
                service=_Service(2),  # type: ignore[arg-type]
            ),
        )
    )

    first = pool.try_acquire()
    second = pool.try_acquire()

    assert first is not None and first.key == PRIMARY_WORKER
    assert second is not None and second.key == SECOND_WORKER
    assert pool.try_acquire() is None
    pool.release(first)
    pool.release(second)


def test_pool_binds_each_operation_to_its_reserved_worker() -> None:
    async def run() -> None:
        pool = HeadlessPool(
            (
                HeadlessWorker(
                    key=PRIMARY_WORKER,
                    service=_Service(1),  # type: ignore[arg-type]
                ),
                HeadlessWorker(
                    key=SECOND_WORKER,
                    service=_Service(2),  # type: ignore[arg-type]
                ),
            )
        )
        first = pool.try_acquire()
        second = pool.try_acquire()
        assert first is not None and second is not None

        async def current_game() -> int:
            await asyncio.sleep(0)
            return cast("int", pool.get_game())

        assert await asyncio.gather(
            pool.run_on(first, current_game),
            pool.run_on(second, current_game),
        ) == [1, 2]
        assert pool.busy_count == 0

    asyncio.run(run())


def test_pool_skips_disconnected_worker_when_another_is_healthy() -> None:
    pool = HeadlessPool(
        (
            HeadlessWorker(
                key=PRIMARY_WORKER,
                service=_Service(1, connected=False),  # type: ignore[arg-type]
            ),
            HeadlessWorker(
                key=SECOND_WORKER,
                service=_Service(2),  # type: ignore[arg-type]
            ),
        )
    )

    worker = pool.try_acquire()

    assert worker is not None
    assert worker.key == SECOND_WORKER
