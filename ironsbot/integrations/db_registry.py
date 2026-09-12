# SPDX-License-Identifier: MIT
import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack, closing, contextmanager

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

    @staticmethod
    def _create_memory_engine() -> Engine:
        """创建一个共享连接的内存 SQLite 引擎。"""
        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    def register(self, name: str) -> None:
        """注册一个命名的内存数据库引擎。若同名引擎已存在，先释放旧引擎。"""
        if name in self._engines:
            self._engines[name].dispose()
        self._engines[name] = self._create_memory_engine()
        logger.debug(f"已注册内存数据库引擎 '{name}'")

    def get_engine(self, name: str) -> Engine | None:
        """获取指定名称的数据库引擎。"""
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

        old_engine = self._engines.get(name)
        self._engines[name] = new_engine
        if old_engine is not None:
            old_engine.dispose()
        logger.debug(f"已从文件导入数据到内存数据库 '{name}'")
        self._notify_loaded(name)

    @contextmanager
    def session(self, name: str) -> Iterator[SQLModelSession | None]:
        engine = self.get_engine(name)
        if engine is None:
            yield None
            return
        with SQLModelSession(engine) as session:
            yield session

    @contextmanager
    def all_sessions(self) -> Iterator[dict[str, SQLModelSession]]:
        with ExitStack() as stack:
            yield {
                name: stack.enter_context(SQLModelSession(engine))
                for name, engine in self._engines.items()
            }

    def close(self) -> None:
        for engine in self._engines.values():
            engine.dispose()
        self._engines.clear()
        self._load_listeners.clear()
        self._load_validators.clear()

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
