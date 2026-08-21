# SPDX-License-Identifier: MIT
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.engine.base import Engine
from sqlmodel import Session as SQLModelSession
from sqlmodel import SQLModel, col, create_engine

from .models import PushRecord, Subscription, Topic


class PushStorage:
    """推送插件的持久化层：SQLModel + 文件 SQLite。

    所有方法均为同步轻量本地操作，在事件循环中直接执行（无 await 切换点，
    天然串行，与项目内其他 SQLModel 用法一致）。引擎与表结构懒初始化，
    供插件在模块级注册主题时直接调用。

    说明：统一使用 SQLAlchemy 原生的 ``Session.execute`` 而非 SQLModel 的
    ``Session.exec``。SQLModel 的 ``exec`` 泛型重载在部分类型检查器（基于
    pyright）下无法正确推断，导致多语句文件出现误报；``execute`` 类型稳定。
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._engine: Engine | None = None

    def _get_engine(self) -> Engine:
        if self._engine is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._engine = create_engine(
                f"sqlite:///{self._db_path}",
                connect_args={"check_same_thread": False},
            )
            SQLModel.metadata.create_all(self._engine)
        return self._engine

    @contextmanager
    def _session(self) -> Generator[SQLModelSession]:
        engine = self._get_engine()
        with SQLModelSession(engine) as session:
            yield session

    # ---- 主题 ----

    def upsert_topic(self, topic: Topic) -> None:
        """插入或更新主题。已存在时保留 DB 中的 enabled/allow_subscribe，
        仅更新 name/description（避免代码重启重置管理员停用状态）。"""
        with self._session() as session:
            existing = session.get(Topic, topic.id)
            if existing is not None:
                existing.name = topic.name
                existing.description = topic.description
                session.add(existing)
            else:
                session.add(topic)
            session.commit()

    def get_topic(self, topic_id: str) -> Topic | None:
        with self._session() as session:
            return session.get(Topic, topic_id)

    def list_topics(self) -> list[Topic]:
        with self._session() as session:
            return list(
                session.execute(select(Topic).order_by(col(Topic.id))).scalars().all()
            )

    def delete_topic(self, topic_id: str) -> bool:
        """删除主题及其订阅、历史，返回主题是否存在。"""
        with self._session() as session:
            topic = session.get(Topic, topic_id)
            if topic is None:
                return False
            session.delete(topic)
            session.execute(
                delete(Subscription).where(col(Subscription.topic_id) == topic_id)
            )
            session.execute(
                delete(PushRecord).where(col(PushRecord.topic_id) == topic_id)
            )
            session.commit()
            return True

    def update_topic(
        self,
        topic_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        allow_subscribe: bool | None = None,
        enabled: bool | None = None,
    ) -> bool:
        with self._session() as session:
            topic = session.get(Topic, topic_id)
            if topic is None:
                return False
            if name is not None:
                topic.name = name
            if description is not None:
                topic.description = description
            if allow_subscribe is not None:
                topic.allow_subscribe = allow_subscribe
            if enabled is not None:
                topic.enabled = enabled
            session.add(topic)
            session.commit()
            return True

    # ---- 订阅 ----

    def add_subscription(self, sub: Subscription) -> bool:
        """新增订阅；已存在时返回 False。"""
        with self._session() as session:
            existing = session.get(Subscription, (sub.topic_id, sub.target))
            if existing is not None:
                return False
            session.add(sub)
            session.commit()
            return True

    def remove_subscription(self, topic_id: str, target: str) -> bool:
        with self._session() as session:
            sub = session.get(Subscription, (topic_id, target))
            if sub is None:
                return False
            session.delete(sub)
            session.commit()
            return True

    def list_subscriptions(self, topic_id: str) -> list[Subscription]:
        with self._session() as session:
            return list(
                session.execute(
                    select(Subscription)
                    .where(col(Subscription.topic_id) == topic_id)
                    .order_by(col(Subscription.subscribed_at))
                )
                .scalars()
                .all()
            )

    def list_subscriptions_by_target(self, target: str) -> list[Subscription]:
        with self._session() as session:
            return list(
                session.execute(
                    select(Subscription)
                    .where(col(Subscription.target) == target)
                    .order_by(col(Subscription.topic_id))
                )
                .scalars()
                .all()
            )

    # ---- 推送历史 ----

    def add_history(self, record: PushRecord, max_count: int) -> None:
        """写入一条推送历史，并按每主题条数上限清理最旧记录。"""
        with self._session() as session:
            session.add(record)
            session.commit()
            if record.topic_id is None:
                return
            stale = (
                session.execute(
                    select(PushRecord)
                    .where(col(PushRecord.topic_id) == record.topic_id)
                    .order_by(col(PushRecord.id).desc())
                    .offset(max_count)
                )
                .scalars()
                .all()
            )
            stale_ids = [r.id for r in stale if r.id is not None]
            if stale_ids:
                session.execute(
                    delete(PushRecord).where(col(PushRecord.id).in_(stale_ids))
                )
                session.commit()

    def has_recent_dedup(
        self, topic_id: str, dedup_key: str, window_seconds: int
    ) -> bool:
        """窗口内是否存在同主题同 dedup_key 的成功推送记录。"""
        now = time.time()
        with self._session() as session:
            statement = (
                select(PushRecord)
                .where(col(PushRecord.topic_id) == topic_id)
                .where(col(PushRecord.dedup_key) == dedup_key)
                .where(col(PushRecord.ok).is_(True))
                .where(col(PushRecord.created_at) >= now - window_seconds)
                .limit(1)
            )
            return session.execute(statement).scalars().first() is not None

    def list_history(self, topic_id: str, limit: int = 20) -> list[PushRecord]:
        with self._session() as session:
            return list(
                session.execute(
                    select(PushRecord)
                    .where(col(PushRecord.topic_id) == topic_id)
                    .order_by(col(PushRecord.id).desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )
