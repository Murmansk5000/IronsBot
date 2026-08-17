# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json
import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple, overload

import httpx
from nonebot import logger

from ironsbot.plugins.headless_seer.packets.head import HeadInfo
from ironsbot.plugins.headless_seer.packets.peak import DailyRankList

from .command_id import COMMAND_ID
from .core import SeerConnect, SeerEncryptConnect
from .exception import ClientNotInitializedError
from .packets import (
    MoreInfo,
    OnLineInfo,
    SimpleTeamInfo,
    UserInfo,
)
from .packets.login import SessionPackct
from .packets.peak import DailyRankInfo, DailyRankParam
from .type_hint import CommandID, SocketRecvPacketBody, T_Deserializable


class Address(NamedTuple):
    host: str
    port: int


@dataclass(slots=True)
class PeakData:
    current_score: int
    current_highest_score: int
    history_highest_score: int


@dataclass(slots=True)
class PeakItemData:
    id: int
    count: int
    win: int
    ban_count: int | None = None

    @property
    def win_rate(self) -> float:
        if self.count == 0:
            return 0
        return round(self.win / self.count * 100, 2)


class PeakType(Enum):
    STANDARD = 1
    WILD = 2
    EXPERT = 3


PEAK_TYPE_NAME_MAP = {
    PeakType.STANDARD: "竞技",
    PeakType.WILD: "狂野",
    PeakType.EXPERT: "专家",
}

PEAK_PET_KEY_MAP = {
    PeakType.STANDARD: (177, 93, 94),
    PeakType.WILD: (185, 184, 183),
    PeakType.EXPERT: (202, 201, 200),
}

PEAK_SUIT_KEY_MAP = {
    PeakType.STANDARD: (173, 174),
    PeakType.WILD: (186, 187),
    PeakType.EXPERT: (203, 204),
}

PEAK_TITLE_KEY_MAP = {
    PeakType.STANDARD: (175, 176),
    PeakType.WILD: (188, 189),
    PeakType.EXPERT: (205, 206),
}


PEAK_USER_KEY_MAP = {
    PeakType.STANDARD: 120,
    PeakType.WILD: 182,
    PeakType.EXPERT: 199,
}


def _merge_win_and_count_rank(
    win_body: DailyRankList,
    count_body: DailyRankList,
    *,
    length: int = 10,
) -> list[PeakItemData]:
    dict_map = {item.id: item for item in win_body.rank_list}
    items = [
        PeakItemData(
            id=item.id,
            count=item.score,
            win=dict_map[item.id].score if item.id in dict_map else 0,
        )
        for item in count_body.rank_list[:length]
    ]
    return sorted(items, key=lambda x: x.count, reverse=True)


class SeerGame:
    def __init__(
        self,
        user_id: int,
        password: str,
        *,
        login_server_url: str,
        heartbeat_interval: float | None = None,
        reconnect_retries: int = 0,
        reconnect_delay: float = 5.0,
        reconnect_delay_max: float = 120.0,
    ) -> None:
        self.user_id = user_id
        self._password: str = password
        self._impl: SeerEncryptConnect | None = None
        self._is_logged_in = False
        self._lock = asyncio.Lock()
        self._heartbeat_interval = heartbeat_interval
        self._reconnect_retries = reconnect_retries
        self._reconnect_delay = reconnect_delay
        self._reconnect_delay_max = reconnect_delay_max
        self._reconnect_task: asyncio.Task[None] | None = None
        self._login_server_url: str = login_server_url

    @property
    def is_logged_in(self) -> bool:
        return self._impl is not None and self._impl.is_connected and self._is_logged_in

    @property
    def client(self) -> SeerEncryptConnect:
        if self._impl is None:
            raise ClientNotInitializedError
        return self._impl

    @overload
    async def send_and_wait(
        self,
        command_id: CommandID[T_Deserializable],
        *body: object,
        timeout: float = 10.0,
    ) -> tuple[HeadInfo, T_Deserializable]: ...
    @overload
    async def send_and_wait(
        self,
        command_id: CommandID,
        *body: object,
        timeout: float = 10.0,
    ) -> tuple[HeadInfo, SocketRecvPacketBody]: ...
    async def send_and_wait(
        self,
        command_id: CommandID,
        *body: object,
        timeout: float = 10.0,
    ) -> tuple[HeadInfo, SocketRecvPacketBody]:
        """发送封包并等待响应，自动附加 user_id。"""
        return await self.client.send_and_wait(
            command_id, self.user_id, *body, timeout=timeout
        )

    async def _send_heartbeat(self) -> None:
        """心跳回调，由连接层周期性调用。"""
        logger.info(f"{self.user_id}：发送心跳包")
        await self.get_team_info(8847403)

    async def login(self) -> None:
        """完整的登录流程：登录服务器认证 -> 获取服务器列表 -> 连接游戏服务器。"""
        session = await self._fetch_session_token(str(self.user_id), self._password)
        async with self._lock:
            if self._impl is not None:
                self._impl.disconnect()
                self._impl = None

            address = await self._fetch_login_server_addr(self._login_server_url)
            login_client = await SeerConnect.new_client(*address)

            try:
                _head, svr_list_info = await login_client.send_and_wait(
                    COMMAND_ID.COMMEND_ONLINE,
                    self.user_id,
                    SessionPackct(session=session),
                    timeout=20.0,
                )
                logger.info("登录认证成功")
                if not svr_list_info.svr_list:
                    raise RuntimeError("登录失败，服务器列表为空")

                servers = [
                    server for server in svr_list_info.svr_list if server.online_id > 0
                ]
                if not servers:
                    raise RuntimeError("登录失败，服务器列表为空")

                server = random.choice(servers)
                await login_client.send_and_wait(
                    COMMAND_ID.RANGE_ONLINE,
                    self.user_id,
                    server.online_id,
                    server.online_id,
                    0,
                    timeout=20.0,
                )

                ip = server.ip.strip(b"\x00").decode("utf-8")
                port = server.port
            finally:
                login_client.disconnect()

            impl = SeerEncryptConnect(
                asyncio.get_running_loop(),
                heartbeat_interval=self._heartbeat_interval,
                on_heartbeat=self._send_heartbeat,
                on_disconnect=self._handle_disconnect,
            )
            try:
                await impl.connect(ip, port)
                await asyncio.sleep(5)
                _head, res = await impl.send_and_wait(
                    COMMAND_ID.LOGIN_IN,
                    self.user_id,
                    self.build_login_packet(session),
                )
                if len(res) == 0:
                    raise RuntimeError("登录失败，响应为空")
            except BaseException as e:
                logger.opt(exception=False).error(f"{self.user_id}：登录失败，原因 {e}")
                impl.disconnect()
                raise

            # self._impl.key = decrypt.clac_encrypt_key(res, self.user_id)
            self._impl = impl
            self._is_logged_in = True
            logger.info("成功进入游戏服务器")

    def logout(self) -> None:
        self._stop_reconnect()
        if self._impl is not None:
            self._impl.disconnect()
        self._is_logged_in = False

    async def _handle_disconnect(self) -> None:
        """连接断开回调，由传输层触发。"""
        self._is_logged_in = False
        logger.warning(f"{self.user_id}：连接已断开")
        self.schedule_reconnect()

    def schedule_reconnect(self) -> None:
        """触发自动重连。若重连任务已在运行或未启用重连则跳过。"""
        if self._reconnect_retries == 0:
            return
        if self._reconnect_task is not None and not self._reconnect_task.done():
            logger.debug(f"{self.user_id}：重连任务已在运行，跳过")
            return
        self._reconnect_task = asyncio.create_task(self._auto_reconnect())

    async def _auto_reconnect(self) -> None:
        """带指数退避的游戏级自动重连，重新执行完整登录流程。

        reconnect_retries < 0 时无限重试，> 0 时重试指定次数。
        """
        assert self._password is not None and self._login_server_url is not None
        delay = self._reconnect_delay
        infinite = self._reconnect_retries < 0
        attempt = 0
        while infinite or attempt < self._reconnect_retries:
            attempt += 1
            retries_label = "∞" if infinite else str(self._reconnect_retries)
            logger.info(
                f"{self.user_id}：将在 {delay:.1f}s 后尝试重连 "
                f"({attempt}/{retries_label})"
            )

            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

            try:
                await self.login()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.opt(exception=True).warning(
                    f"{self.user_id}：重连失败 ({attempt}/{retries_label})"
                )
            else:
                logger.info(f"{self.user_id}：重连成功")
                return

            delay = min(delay * 2, self._reconnect_delay_max)

        logger.error(
            f"{self.user_id}：已达最大重试次数 ({self._reconnect_retries})，放弃重连"
        )

    def _stop_reconnect(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        self._reconnect_task = None

    async def get_team_info(self, team_id: int) -> SimpleTeamInfo:
        """获取战队信息。"""
        _head, body = await self.send_and_wait(COMMAND_ID.TEAM_GET_INFO, team_id)
        return body

    async def get_user_info(self, user_id: int) -> UserInfo:
        """获取用户信息。"""
        _head, body = await self.send_and_wait(COMMAND_ID.GET_USER_INFO, user_id)
        return body

    async def get_more_user_info(self, user_id: int) -> MoreInfo:
        """获取用户详细信息（注册时间、成就、精灵数等）。"""
        _head, body = await self.send_and_wait(COMMAND_ID.GET_MORE_USER_INFO, user_id)
        return body

    async def get_limit_pool_vote(self, sub_key: int) -> DailyRankList:
        """获取巅峰限制池投票排行榜信息。"""
        _head, body = await self.send_and_wait(
            COMMAND_ID.GET_DAILY_RANK_INFO,
            DailyRankParam(key=191, sub_key=sub_key, start=0, end=19),
        )
        return body

    async def get_semi_limit_pool_vote(self, sub_key: int) -> DailyRankList:
        """获取巅峰准限制池投票排行榜信息。"""
        _head, body = await self.send_and_wait(
            COMMAND_ID.GET_DAILY_RANK_INFO,
            DailyRankParam(key=192, sub_key=sub_key, start=0, end=29),
        )
        return body

    async def get_peak_suit_rank(
        self, sub_key: int, peak_type: PeakType
    ) -> list[PeakItemData]:
        count_key, win_key = PEAK_SUIT_KEY_MAP[peak_type]
        count_body, win_body = await asyncio.gather(
            self.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                DailyRankParam(key=count_key, sub_key=sub_key, start=0, end=19),
            ),
            self.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                DailyRankParam(key=win_key, sub_key=sub_key, start=0, end=19),
            ),
        )  # 胜场数
        return _merge_win_and_count_rank(win_body[1], count_body[1])

    async def get_peak_title_rank(
        self, sub_key: int, peak_type: PeakType
    ) -> list[PeakItemData]:
        count_key, win_key = PEAK_TITLE_KEY_MAP[peak_type]
        count_body, win_body = await asyncio.gather(
            self.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                DailyRankParam(key=count_key, sub_key=sub_key, start=0, end=19),
            ),
            self.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                DailyRankParam(key=win_key, sub_key=sub_key, start=0, end=19),
            ),
        )
        return _merge_win_and_count_rank(win_body[1], count_body[1])

    async def get_peak_pet_rank(
        self, sub_key: int, peak_type: PeakType
    ) -> tuple[list[PeakItemData], DailyRankList]:
        key_1, key_2, key_3 = PEAK_PET_KEY_MAP[peak_type]
        win_body, count_body, ban_body = await asyncio.gather(
            self.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                DailyRankParam(key=key_1, sub_key=sub_key, start=0, end=29),
            ),
            self.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                DailyRankParam(key=key_2, sub_key=sub_key, start=0, end=29),
            ),
            self.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                DailyRankParam(key=key_3, sub_key=sub_key, start=0, end=19),
            ),
        )
        return (
            _merge_win_and_count_rank(win_body[1], count_body[1], length=20),
            ban_body[1],
        )

    async def get_peak_user_rank(
        self, sub_key: int, peak_type: PeakType
    ) -> list[DailyRankInfo]:
        key = PEAK_USER_KEY_MAP[peak_type]
        result: tuple[HeadInfo, DailyRankList] = await self.send_and_wait(
            COMMAND_ID.GET_DAILY_RANK_INFO,
            DailyRankParam(key=key, sub_key=sub_key, start=0, end=19),
        )
        return result[1].rank_list

    async def get_user_peak_expert_data(self, user_id: int) -> PeakData:
        result = await asyncio.gather(
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 129441),
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 129442),
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 129443),
        )
        return PeakData(
            current_score=result[0][1].value,
            current_highest_score=result[1][1].value,
            history_highest_score=result[2][1].value,
        )

    async def get_user_peak_data(self, user_id: int) -> PeakData:
        result = await asyncio.gather(
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 124801),
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 124802),
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 124800),
        )
        return PeakData(
            current_score=result[0][1].value,
            history_highest_score=result[1][1].value,
            current_highest_score=result[2][1].value,
        )

    async def get_user_peak_wild_data(self, user_id: int) -> PeakData:
        result = await asyncio.gather(
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 124790),
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 124791),
            self.send_and_wait(COMMAND_ID.USER_FOREVER_VALUE, user_id, 124792),
        )
        return PeakData(
            current_highest_score=result[0][1].value,
            current_score=result[1][1].value,
            history_highest_score=result[2][1].value,
        )

    async def get_user_online_info(self, user_id: int) -> OnLineInfo | None:
        """当用户不在线时返回 None。"""
        _head, body = await self.send_and_wait(COMMAND_ID.SEE_ONLINE, 1, user_id)
        try:
            return body.infos[0]
        except IndexError:
            return None

    @staticmethod
    async def _fetch_login_server_addr(url: str) -> Address:
        async with httpx.AsyncClient() as http:
            resp = await http.get(url)
            resp.raise_for_status()
            text = resp.text.strip()
        all_server_addr = text.split("|")
        addr = random.choice(all_server_addr).split(":")
        return Address(addr[0], int(addr[1]))

    @staticmethod
    async def _fetch_session_token(account: str, password: str) -> bytes:
        timestamp = str(int(time.time() * 1000))
        callback = f"jQuery19008830978978300397_{timestamp}"
        params = {
            "r": "userIdentity/authenticate",
            "callback": callback,
            "account": account,
            "rememberAcc": "false",
            "passwd": password,
            "rememberPwd": "true",
            "vericode": "",
            "game": "02",
            "tad": "none",
            "_": timestamp,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://account-co.61.com/index.php", params=params
            )
            response.raise_for_status()

        payload = SeerGame.parse_jsonp(response.text.strip(), callback)
        if payload.get("result") != 0:
            err_msg = payload.get("err_desc") or payload
            raise ValueError(f"登录失败: {err_msg}")
        data = payload.get("data") or {}
        if not (session := data.get("session")):
            raise ValueError("响应中缺少 session")
        try:
            return bytes.fromhex(session)
        except ValueError as exc:
            raise ValueError("session 格式错误") from exc

    @staticmethod
    def parse_jsonp(response_text: str, expected_callback: str | None = None) -> dict:
        suffix = ");"
        if not response_text.endswith(suffix):
            raise ValueError("回调格式不正确")
        open_paren = response_text.find("(")
        if open_paren == -1:
            raise ValueError("响应缺少括号")
        actual_callback = response_text[:open_paren]
        if expected_callback and not actual_callback.startswith(expected_callback):
            raise ValueError(f"回调名称不匹配: {actual_callback}")
        json_text = response_text[open_paren + 1 : -len(suffix)]
        return json.loads(json_text)

    @staticmethod
    def build_login_packet(session_bytes: bytes) -> bytes:
        return session_bytes + bytearray.fromhex(
            "74616F6D65650000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000B38000000015043000000000000000000000000000000002710000000010000000100000002756E6974795F6170705F74616F6D656500000000000000000000000000000000636F6D2E74616F6D65652E736565722E6D6F62696C65000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000004E6974726F414E3531352D35352841636572290000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        )
