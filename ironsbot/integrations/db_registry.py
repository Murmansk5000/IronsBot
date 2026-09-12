# SPDX-License-Identifier: MIT
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import ExitStack, closing, contextmanager
from threading import RLock
from types import MappingProxyType

from sqlalchemy.engine.base import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session as SQLModelSession
from sqlmodel import create_engine

from ironsbot.integrations.storage.sqlite import open_sqlite_connection

logger = logging.getLogger(__name__)
DatabaseLoadListener = Callable[[], object]
DatabaseLoadValidator = Callable[[Engine], object]


class DatabaseManager:
    """管理多个命名内存数据库引擎的管理器。

    每个数据库通过唯一的名称标识，数据存储在内存中，
    通过从远程 SQLite 文件导入数据来更新。
    """

    def __init__(self) -> None:
        self._engines: dict[str, Engine] = {}
        self._load_listeners: dict[str, list[DatabaseLoadListener]] = {}
        self._load_validators: dict[str, list[DatabaseLoadValidator]] = {}
        self._lock = RLock()
        self._leases: dict[Engine, int] = {}
        self._retired: set[Engine] = set()

    @staticmethod
    def _create_memory_engine() -> Engine:
        """创建一个共享连接的内存 SQLite 引擎。"""
        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    def register(self, name: str) -> None:
        """Register a new engine; active snapshots retain the previous one."""
        self._replace_engine(name, self._create_memory_engine())
        logger.debug(f"已注册内存数据库引擎 '{name}'")

    def get_engine(self, name: str) -> Engine | None:
        """获取指定名称的数据库引擎。"""
        with self._lock:
            return self._engines.get(name)

    def add_load_listener(
        self,
        name: str,
        listener: DatabaseLoadListener,
    ) -> None:
        """注册数据库成功换版后的同步观察器。"""
        self._load_listeners.setdefault(name, []).append(listener)

    def add_load_validator(
        self,
        name: str,
        validator: DatabaseLoadValidator,
    ) -> None:
        """Register a validation step for a staged database before replacement."""
        self._load_validators.setdefault(name, []).append(validator)

    def load_from_file(self, name: str, file_path: str) -> None:
        """从 SQLite 文件导入全部数据到新的内存引擎，然后原子替换旧引擎。"""
        new_engine = self._create_memory_engine()

        try:
            with closing(open_sqlite_connection(file_path, read_only=True)) as source:
                raw_conn = new_engine.raw_connection()
                try:
                    source.backup(raw_conn.dbapi_connection)  # pyright: ignore[reportArgumentType]
                finally:
                    raw_conn.close()
            self._validate_loaded(name, new_engine)
        except BaseException:
            new_engine.dispose()
            raise

        self._replace_engine(name, new_engine)
        logger.debug(f"已从文件导入数据到内存数据库 '{name}'")
        self._notify_loaded(name)

    @contextmanager
    def session(self, name: str) -> Iterator[SQLModelSession | None]:
        with self.snapshot((name,)) as engines:
            engine = engines.get(name)
            if engine is None:
                yield None
                return
            with SQLModelSession(engine) as session:
                yield session

    @contextmanager
    def all_sessions(self) -> Iterator[dict[str, SQLModelSession]]:
        with self.snapshot() as engines, ExitStack() as stack:
            yield {
                name: stack.enter_context(SQLModelSession(engine))
                for name, engine in engines.items()
            }

    def close(self) -> None:
        with self._lock:
            for engine in self._engines.values():
                self._retire_engine(engine)
            self._engines.clear()
            self._load_listeners.clear()
            self._load_validators.clear()

    @contextmanager
    def snapshot(
        self,
        names: Iterable[str] | None = None,
    ) -> Iterator[Mapping[str, Engine]]:
        """Keep selected engine generations alive without opening SQL sessions."""
        with self._lock:
            selected = {
                name: self._engines[name]
                for name in (self._engines if names is None else names)
                if name in self._engines
            }
            for engine in selected.values():
                self._leases[engine] = self._leases.get(engine, 0) + 1
        try:
            yield MappingProxyType(selected)
        finally:
            with self._lock:
                for engine in selected.values():
                    remaining = self._leases[engine] - 1
                    if remaining:
                        self._leases[engine] = remaining
                    else:
                        del self._leases[engine]
                        if engine in self._retired:
                            self._retired.remove(engine)
                            engine.dispose()

    def _replace_engine(self, name: str, engine: Engine) -> None:
        with self._lock:
            previous = self._engines.get(name)
            self._engines[name] = engine
            if previous is not None:
                self._retire_engine(previous)

    def _retire_engine(self, engine: Engine) -> None:
        if self._leases.get(engine, 0):
            self._retired.add(engine)
        else:
            engine.dispose()

    def _validate_loaded(self, name: str, engine: Engine) -> None:
        for validator in self._load_validators.get(name, ()):
            validator(engine)

    def _notify_loaded(self, name: str) -> None:
        for listener in self._load_listeners.get(name, ()):
            self._run_load_listener(name, listener)

    @staticmethod
    def _run_load_listener(name: str, listener: DatabaseLoadListener) -> None:
        try:
            listener()
        except Exception:
            logger.exception("数据库 '%s' 换版观察器执行失败", name)
