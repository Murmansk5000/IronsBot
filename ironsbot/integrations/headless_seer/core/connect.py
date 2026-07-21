# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import logging
import struct
from abc import abstractmethod
from asyncio import BaseTransport, StreamReader, StreamReaderProtocol, StreamWriter
from collections import defaultdict, deque
from collections.abc import Callable, Coroutine, Iterable
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Any, Generic, TypeGuard, TypeVar, overload

from typing_extensions import Self, TypeVarTuple, Unpack

from ironsbot.core.tasks import TaskSpawner
from ironsbot.services.operations.headless_errors import SocketRecvError

from .. import decrypt
from ..as3bytearray import AS3ByteArray
from ..command_id import COMMAND_ID
from ..packet.packet import Deserializable
from ..packets.head import HeadInfo
from ..packets.registry import PACKET_BODY_TYPES
from ..type_hint import (
    Buffer,
    CommandID,
    Listener,
    SocketRecvPacketBody,
    T_Deserializable,
)
from .listener import EventListener

_T_CommandID = TypeVar("_T_CommandID", bound=CommandID)
_T_UnpackedType = TypeVarTuple("_T_UnpackedType")
logger = logging.getLogger(__name__)
DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0


def _serialize_binary(data: AS3ByteArray, *args: Any) -> None:
    for i in args:
        if isinstance(i, Deserializable):
            data.write_bytes(i.pack())
        elif isinstance(i, str):
            data.write_bytes(i.encode("utf-8"))
        elif isinstance(i, Buffer):
            data.write_bytes(i)
        elif isinstance(i, Iterable):
            _serialize_binary(data, *i)
        else:
            data.write_uint32(i)


class ClientReaderProtocol(StreamReaderProtocol):
    def connection_made(self, transport: BaseTransport) -> None:
        super().connection_made(transport)
        logger.info(f"已连接到服务器 {transport.get_extra_info('peername')}")

    def connection_lost(self, exc: Exception | None) -> None:
        super().connection_lost(exc)
        logger.info("已断开服务器连接")


def _writer_is_connected(
    writer: StreamWriter | None,
) -> TypeGuard[StreamWriter]:
    return writer is not None and not writer.is_closing()


class AbstractSocketConnect(
    AbstractAsyncContextManager, Generic[_T_CommandID, Unpack[_T_UnpackedType]]
):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        spawn: TaskSpawner,
        event_listener: EventListener[_T_CommandID, Unpack[_T_UnpackedType]]
        | None = None,
        heartbeat_interval: float | None = None,
        on_heartbeat: Callable[[], Coroutine[Any, Any, None]] | None = None,
        on_disconnect: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._loop = loop
        self._spawn = spawn
        self._reader: StreamReader = StreamReader(limit=2**16, loop=self._loop)
        self._protocol: ClientReaderProtocol = ClientReaderProtocol(
            self._reader, loop=loop
        )
        self._writer: StreamWriter | None = None
        self.event_listener = event_listener or EventListener()
        self._pending_requests: defaultdict[
            _T_CommandID, deque[asyncio.Future[tuple[Unpack[_T_UnpackedType]]]]
        ] = defaultdict(deque)
        # The protocol has no per-request sequence number. Keep one request in
        # flight so a response can never be associated with the wrong caller.
        self._request_lock = asyncio.Lock()
        self._heartbeat_interval = heartbeat_interval
        self._on_heartbeat = on_heartbeat
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._on_disconnect = on_disconnect
        self._disconnect_notify_task: asyncio.Task[None] | None = None
        self._intentional_disconnect = False

    @abstractmethod
    async def send(self, command_id: _T_CommandID, *body: Any) -> _T_CommandID:
        raise NotImplementedError

    @abstractmethod
    async def recv_bytes(self) -> bytes:
        """读取一条封包并返回bytes"""
        raise NotImplementedError

    @abstractmethod
    async def recv_packet(self) -> tuple[Unpack[_T_UnpackedType]] | None:
        raise NotImplementedError

    @property
    def is_connected(self) -> bool:
        return _writer_is_connected(self._writer)

    async def connect(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._intentional_disconnect = False
        transport, _ = await self._loop.create_connection(
            lambda: self._protocol, host=host, port=port
        )
        self._writer = StreamWriter(
            transport, self._protocol, self._reader, loop=self._loop
        )
        self._start_reader()
        self._start_heartbeat()

    def disconnect(self) -> None:
        self._intentional_disconnect = True
        self._stop_reader()
        self._stop_heartbeat()
        self._reject_all_pending(ConnectionError("连接已断开"))
        writer = self._writer
        if _writer_is_connected(writer):
            writer.close()
        self._writer = None

    @classmethod
    async def new_client(
        cls,
        host: str,
        port: int,
        *,
        spawn: TaskSpawner,
        event_listener: EventListener[_T_CommandID, Unpack[_T_UnpackedType]]
        | None = None,
    ) -> Self:
        client = cls(
            asyncio.get_running_loop(),
            spawn=spawn,
            event_listener=event_listener,
        )
        await client.connect(host, port)
        return client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool | None:
        self.disconnect()
        return not (
            exc_type is not None
            and issubclass(exc_type, (RuntimeError, ConnectionError))
        )

    def add_cmd_listener(
        self,
        command_id: _T_CommandID,
        *,
        callback: Listener[Unpack[_T_UnpackedType]],
        disposable: bool = False,
    ) -> Listener[Unpack[_T_UnpackedType]]:
        return self.event_listener.add_listener(command_id, callback, disposable)

    def remove_cmd_listener(
        self,
        command_id: _T_CommandID,
        *,
        callback: Listener[Unpack[_T_UnpackedType]],
    ) -> None:
        self.event_listener.remove_listener(command_id, callback)

    # ---- 读循环 ----

    async def _read_loop(self) -> None:
        """单一持续读循环，顺序处理所有到达的封包。"""
        try:
            while self.is_connected:
                try:
                    result = await self.recv_packet()
                except (ConnectionError, asyncio.IncompleteReadError):
                    logger.exception("错误")
                    break
                except Exception:
                    logger.warning("处理封包时出错", exc_info=True)
                    if not self.is_connected:
                        break
                    continue
                if result is None:
                    logger.error("收到空封包")
                    break
        except asyncio.CancelledError:
            return
        self._on_connection_lost()

    def _on_connection_lost(self) -> None:
        """读循环正常退出（连接断开）后的清理。"""
        if (
            self._writer is None
            and self._reader_task is None
            and not self._pending_requests
        ):
            return
        self._reader_task = None
        self._stop_heartbeat()
        self._reject_all_pending(ConnectionError("连接已断开"))
        writer = self._writer
        if _writer_is_connected(writer):
            writer.close()
        self._writer = None
        if (
            not self._intentional_disconnect
            and self._on_disconnect
            and (
                self._disconnect_notify_task is None
                or self._disconnect_notify_task.done()
            )
        ):
            self._disconnect_notify_task = self._spawn(
                self._on_disconnect(),
                name="headless-disconnect-notify",
            )

    def _start_reader(self) -> None:
        self._stop_reader()
        self._reader_task = self._spawn(
            self._read_loop(),
            name="headless-socket-reader",
        )

    def _stop_reader(self) -> None:
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
        self._reader_task = None

    def _reset_transport(self) -> None:
        """重置内部 StreamReader 和 Protocol，为新连接做准备。"""
        self._reader = StreamReader(limit=2**16, loop=self._loop)
        self._protocol = ClientReaderProtocol(self._reader, loop=self._loop)
        self._writer = None

    # ---- 心跳 ----

    async def _heartbeat_loop(self) -> None:
        if self._heartbeat_interval is None or self._on_heartbeat is None:
            raise RuntimeError
        connection_lost = False
        try:
            while self.is_connected:
                await asyncio.sleep(self._heartbeat_interval)
                if not self.is_connected:
                    break
                try:
                    await self._on_heartbeat()
                except (
                    asyncio.TimeoutError,
                    BrokenPipeError,
                    ConnectionError,
                    OSError,
                ) as e:
                    logger.warning(f"心跳包发送失败，准备重连: {e}")
                    connection_lost = True
                    break
        except asyncio.CancelledError:
            return

        if connection_lost:
            self._on_connection_lost()

    def _start_heartbeat(self) -> None:
        if self._heartbeat_interval is None or self._on_heartbeat is None:
            return
        self._stop_heartbeat()
        self._heartbeat_task = self._spawn(
            self._heartbeat_loop(),
            name="headless-heartbeat",
        )

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    # ---- 请求-响应关联 ----

    async def send_and_wait(
        self,
        command_id: _T_CommandID,
        *body: Any,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> tuple[Unpack[_T_UnpackedType]]:
        """发送封包并等待对应 cmd_id 的响应，FIFO 顺序关联。"""
        async with self._request_lock:
            future: asyncio.Future[tuple[Unpack[_T_UnpackedType]]] = (
                self._loop.create_future()
            )
            self._pending_requests[command_id].append(future)
            try:
                await self.send(command_id, *body)
            except BaseException:
                self._discard_pending(command_id, future)
                future.cancel()
                raise

            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                future.cancel()
                logger.warning(
                    "headless request interrupted; reconnecting: command_id=%s",
                    command_id,
                )
                self._on_connection_lost()
                raise

    def _discard_pending(
        self,
        command_id: _T_CommandID,
        future: asyncio.Future[Any],
    ) -> None:
        pending = self._pending_requests.get(command_id)
        if pending is None:
            return
        try:
            pending.remove(future)
        except ValueError:
            return
        if not pending:
            del self._pending_requests[command_id]

    def _pop_pending(self, command_id: _T_CommandID) -> asyncio.Future | None:
        """弹出 pending 队列中的第一个 Future，没有则返回 None。"""
        pending = self._pending_requests.get(command_id)
        if not pending:
            return None
        future = pending.popleft()
        if not pending:
            del self._pending_requests[command_id]
        return future

    def _resolve_pending(
        self, command_id: _T_CommandID, *args: Unpack[_T_UnpackedType]
    ) -> bool:
        """尝试用结果解析 pending 队列中的第一个 Future，成功返回 True。"""
        future = self._pop_pending(command_id)
        if future is None:
            return False
        if not future.done():
            future.set_result(args)
        return True

    def _reject_pending(self, command_id: _T_CommandID, exc: BaseException) -> bool:
        """尝试用异常拒绝 pending 队列中的第一个 Future，成功返回 True。"""
        future = self._pop_pending(command_id)
        if future is None:
            return False
        if not future.done():
            future.set_exception(exc)
        return True

    def _reject_all_pending(self, exc: BaseException) -> None:
        """用异常拒绝所有挂起的 Future。"""
        for queue in self._pending_requests.values():
            for future in queue:
                if not future.done():
                    future.set_exception(exc)
        self._pending_requests.clear()


class SeerConnect(AbstractSocketConnect[CommandID, HeadInfo, SocketRecvPacketBody]):
    HEAD_LENGTH = 13
    PACKAGE_MAX = 8838608

    async def send(self, command_id: CommandID, *body: Any) -> CommandID:
        writer = self._writer
        if not _writer_is_connected(writer):
            raise BrokenPipeError("Not connected to the server.")

        packet = self.pack(command_id, *body)
        writer.write(packet)
        await writer.drain()
        logger.debug(f"send success: command_id: {command_id}")
        return command_id

    @overload
    async def send_and_wait(
        self,
        command_id: CommandID[T_Deserializable],
        *body: Any,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> tuple[HeadInfo, T_Deserializable]: ...
    @overload
    async def send_and_wait(
        self,
        command_id: CommandID,
        *body: Any,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> tuple[HeadInfo, SocketRecvPacketBody]: ...
    async def send_and_wait(
        self,
        command_id: CommandID,
        *body: Any,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> tuple[HeadInfo, SocketRecvPacketBody]:
        return await super().send_and_wait(command_id, *body, timeout=timeout)

    def pack(self, command_id: int, user_id: int, *body: Any) -> Buffer:
        head = HeadInfo("1", CommandID(command_id), user_id, 0)
        body_bytes = AS3ByteArray()
        _serialize_binary(body_bytes, *body)
        body_bytes = head.pack() + body_bytes
        length = len(body_bytes) + 4
        length_bytes = AS3ByteArray()
        length_bytes.write_uint32(length)
        return length_bytes + body_bytes

    def unpack(self, data: bytes) -> tuple[HeadInfo, SocketRecvPacketBody]:
        if len(data) > self.PACKAGE_MAX:
            raise ValueError("封包长度超过上限")

        headinfo = HeadInfo.unpack(data[: self.HEAD_LENGTH])
        if headinfo.cmd_id > 1001:
            raise ValueError(f"无效的命令 ID: {headinfo.cmd_id}")

        body_data = data[self.HEAD_LENGTH :]
        if body_type := PACKET_BODY_TYPES.get(headinfo.cmd_id):
            return headinfo, body_type.unpack(body_data)
        return headinfo, AS3ByteArray(body_data)

    async def recv_bytes(self) -> bytes:
        """读取一条封包并返回bytes"""
        if not _writer_is_connected(self._writer):
            return b""

        reader = self._reader
        try:
            length_bytes = await reader.readexactly(4)
        except asyncio.IncompleteReadError as e:
            logger.error(
                f"读取长度失败: 期望{e.expected}字节，实际读取{len(e.partial)}字节，内容: {e.partial}"
            )
            return b""

        length = struct.unpack("!I", length_bytes)[0]
        return await reader.readexactly(length - 4)

    async def recv_packet(self) -> tuple[HeadInfo, SocketRecvPacketBody] | None:
        packet_bytes = await self.recv_bytes()
        if not packet_bytes:
            return None

        headinfo = HeadInfo.unpack(packet_bytes[:13])
        try:
            headinfo, body = self.unpack(packet_bytes)
        except Exception as exc:
            self._reject_pending(headinfo.cmd_id, exc)
            raise
        self._resolve_pending(headinfo.cmd_id, headinfo, body)
        self.event_listener.trigger(headinfo.cmd_id, headinfo, body)
        return headinfo, body


class SeerEncryptConnect(SeerConnect):
    HEAD_LENGTH = 13

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        spawn: TaskSpawner,
        event_listener: EventListener[CommandID, HeadInfo, SocketRecvPacketBody]
        | None = None,
        heartbeat_interval: float | None = None,
        on_heartbeat: Callable[[], Coroutine[Any, Any, None]] | None = None,
        on_disconnect: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        super().__init__(
            loop,
            spawn=spawn,
            event_listener=event_listener,
            heartbeat_interval=heartbeat_interval,
            on_heartbeat=on_heartbeat,
            on_disconnect=on_disconnect,
        )
        self._result: int = 0

    @property
    def result(self) -> int:
        return self._result

    def pack(self, command_id: int, user_id: int, *body: Any) -> Buffer:
        body_bytes = AS3ByteArray()
        _serialize_binary(body_bytes, *body)
        if command_id > 1000:
            self._result = decrypt.calculate_result(
                self._result,
                command_id,
                body_bytes,
            )
        head = HeadInfo("1", CommandID(command_id), user_id, self._result)
        # encrypted_body = decrypt.encrypt((head.pack() + body_bytes), self.key)
        body_bytes = head.pack() + body_bytes
        length = len(body_bytes) + 4
        length_bytes = AS3ByteArray()
        length_bytes.write_uint32(length)
        logger.debug(f"pack: head={head!r}, length={length}")
        return length_bytes + body_bytes

    def unpack(self, data: bytes) -> tuple[HeadInfo, SocketRecvPacketBody]:
        # reader = AS3ByteArray(decrypt.decrypt(data, self.key))
        if len(data) < self.HEAD_LENGTH or len(data) > self.PACKAGE_MAX:
            raise ValueError("封包长度异常")

        headinfo = HeadInfo.unpack(data[: self.HEAD_LENGTH])

        if headinfo.cmd_id in (COMMAND_ID.LOGIN_IN, COMMAND_ID.SOCKET_RECONNECT, 42387):
            self._result = headinfo.result

        if headinfo.result >= 1000:
            raise SocketRecvError(headinfo, f"请求失败：{headinfo.result}")

        body_bytes = data[self.HEAD_LENGTH :]
        if body_type := PACKET_BODY_TYPES.get(headinfo.cmd_id):
            return headinfo, body_type.unpack(body_bytes)

        return headinfo, AS3ByteArray(body_bytes)
