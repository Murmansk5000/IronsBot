import re
import time
import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from nonebot import require, get_driver
from nonebot.adapters.onebot.v11 import Bot
from nonebot.log import logger

# 注册 APScheduler
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler

from .config import plugin_config

# =========================================================
# 配置区域
# =========================================================

# B站 UID
BILI_UID = plugin_config.bilibili_monitor_uid

# 自动巡检间隔（分钟）
CHECK_INTERVAL_MINUTES = plugin_config.bilibili_monitor_check_interval_minutes

# 深夜休眠
SLEEP_START_HOUR = plugin_config.bilibili_monitor_sleep_start_hour
SLEEP_END_HOUR = plugin_config.bilibili_monitor_sleep_end_hour
SLEEP_INTERVAL_MINUTES = plugin_config.bilibili_monitor_sleep_interval_minutes

# 群推送目标
TARGET_GROUP_IDS = plugin_config.bilibili_monitor_target_group_ids

# 私聊目标
TARGET_USER_IDS = plugin_config.bilibili_monitor_target_user_ids

# =========================================================

CACHE_FILE = Path(__file__).parent / "last_dynamic_time.txt"
COOKIE_CACHE_FILE = Path(__file__).parent / "bili_cookie_cache.txt"


# =========================================================
# 缓存操作
# =========================================================

def get_last_saved_time() -> int:
    if CACHE_FILE.exists():
        try:
            return int(
                CACHE_FILE.read_text(
                    encoding="utf-8"
                ).strip()
            )
        except:
            return 0
    return 0


def save_last_time(pub_time: int):
    CACHE_FILE.write_text(
        str(pub_time),
        encoding="utf-8"
    )


def get_saved_cookie() -> str:
    if COOKIE_CACHE_FILE.exists():
        return COOKIE_CACHE_FILE.read_text(
            encoding="utf-8"
        ).strip()

    return ""


def save_new_cookie(cookie_str: str):
    COOKIE_CACHE_FILE.write_text(
        cookie_str,
        encoding="utf-8"
    )


# =========================================================
# B站扫码登录
# =========================================================

def trigger_bili_terminal_qrcode():

    logger.warning(
        "🚨 Cookie失效，正在申请B站扫码登录..."
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0"
        )
    }

    try:
        with httpx.Client(
            headers=headers,
            timeout=10.0
        ) as client:

            apply_res = client.get(
                "https://passport.bilibili.com/"
                "x/passport-login/web/qrcode/generate"
            ).json()

            if apply_res.get("code") != 0:
                return None

            qr_data = apply_res.get("data", {})

            qr_url = qr_data.get("url")
            qrcode_key = qr_data.get("qrcode_key")

            import qrcode_terminal

            qrcode_terminal.draw(qr_url)

            print(
                "\n👉 请使用B站APP扫码登录 👈\n"
            )

            for _ in range(36):

                time.sleep(5)

                poll_res = client.get(
                    "https://passport.bilibili.com/"
                    "x/passport-login/web/qrcode/poll",
                    params={
                        "qrcode_key": qrcode_key
                    }
                )

                if (
                    poll_res.json()
                    .get("data", {})
                    .get("code")
                    == 0
                ):

                    cookies_list = [
                        f"{k}={v}"
                        for k, v
                        in poll_res.cookies.items()
                    ]

                    new_cookie = (
                        "; ".join(cookies_list)
                        + ";"
                    )

                    save_new_cookie(new_cookie)

                    logger.info(
                        "✅ B站Cookie刷新成功"
                    )

                    return new_cookie

            logger.warning(
                "⚠️ B站扫码登录超时"
            )

            return None

    except Exception as e:
        logger.error(
            f"扫码登录故障: {e}"
        )

        return None


# =========================================================
# 文本提取
# =========================================================

def scan_and_swallow_all_long_strings(data_obj):

    texts = []

    ignore_keys = [
        "url",
        "src",
        "jump_url",
        "cover",
        "face",
        "card_url",
        "avatar",
        "uri",
    ]

    if isinstance(data_obj, dict):

        for k, v in data_obj.items():

            if k in ignore_keys:
                continue

            if isinstance(v, str):

                val = v.strip()

                if (
                    len(val) >= 15
                    and re.search(
                        r'[\u4e00-\u9fa5]',
                        val
                    )
                ):
                    if (
                        "取消关注" not in val
                        and "举报" not in val
                        and "AUTHOR_TYPE" not in val
                    ):
                        texts.append(val)

            else:
                texts.extend(
                    scan_and_swallow_all_long_strings(v)
                )

    elif isinstance(data_obj, list):

        for item in data_obj:
            texts.extend(
                scan_and_swallow_all_long_strings(item)
            )

    return texts


# =========================================================
# 单动态解析
# =========================================================

def parse_single_item(
    item,
    pub_ts: int,
    menu_mode: bool = False
):

    try:

        dynamic_id = str(
            item.get("id_str") or ""
        )

        modules = item.get("modules") or {}

        module_dynamic = (
            modules.get("module_dynamic") or {}
        )

        time_str = datetime.fromtimestamp(
            pub_ts
        ).strftime("%Y-%m-%d %H:%M:%S")

        image_urls = []

        if "major" in module_dynamic:

            major = (
                module_dynamic.get("major") or {}
            )

            if "draw" in major:

                for pic in (
                    major.get("draw") or {}
                ).get("items", []):

                    if pic.get("src"):
                        image_urls.append(
                            pic.get("src")
                        )

            elif "opus" in major:

                for pic in (
                    major.get("opus") or {}
                ).get("pics", []):

                    if pic.get("url"):
                        image_urls.append(
                            pic.get("url")
                        )

            elif "archive" in major:

                cover = (
                    major.get("archive") or {}
                ).get("cover")

                if cover:
                    image_urls.append(cover)

        all_long_texts = (
            scan_and_swallow_all_long_strings(item)
        )

        unique_pieces = []

        for piece in all_long_texts:

            if (
                piece.strip()
                and piece.strip()
                not in unique_pieces
            ):
                unique_pieces.append(
                    piece.strip()
                )

        content = "\n".join(
            unique_pieces
        ).strip()

        if not content:
            content = "赛尔号发布了一条动态\n回复“动态”查询历史动态"

        cq_images = "".join([
            f"\n[CQ:image,file={img}]"
            for img in image_urls
        ])

        short_content = (
            content[:500] + "..."
            if len(content) > 500
            else content
        )

        tag = (
            "点播详情"
            if menu_mode
            else "动态更新"
        )

        return (
            f"🔔 【B站{tag}】\n"
            f"⏰ 发布时间: {time_str}\n\n"
            f"{short_content}"
            f"{cq_images}\n\n"
            f"传送门: "
            f"https://t.bilibili.com/{dynamic_id}"
        )

    except Exception as e:

        logger.error(
            f"解析动态故障: {e}"
        )

        return None


# =========================================================
# 核心检测逻辑
# =========================================================

async def do_check_logic(
    is_startup_check: bool = False
):

    now = datetime.now()

    # 深夜节能
    if (
        now.hour >= SLEEP_START_HOUR
        or now.hour < SLEEP_END_HOUR
    ):

        if (
            not is_startup_check
            and now.minute
            % SLEEP_INTERVAL_MINUTES != 0
        ):
            logger.info(
                f"🌙 深夜节能模式跳过检测 "
                f"{now.strftime('%H:%M')}"
            )
            return

    current_cookie = get_saved_cookie()

    headers = {
        "User-Agent": (
            "Mozilla/5.0"
        ),
        "Referer": "https://t.bilibili.com/",
        "Cookie": current_cookie,
    }

    list_url = (
        "https://api.bilibili.com/"
        "x/polymer/web-dynamic/v1/feed/all?type=all"
    )

    try:

        async with httpx.AsyncClient(
            headers=headers,
            timeout=10.0,
            follow_redirects=True
        ) as client:

            response = await client.get(list_url)

            if (
                response.status_code != 200
                or response.json().get("code")
                in [-101, -401, -403, 412]
            ):

                fresh_cookie = (
                    trigger_bili_terminal_qrcode()
                )

                if not fresh_cookie:
                    return

                headers["Cookie"] = fresh_cookie

                response = await client.get(list_url)

            res_json = response.json()

            if res_json.get("code") != 0:
                return

            valid_dynamics = []

            for item in (
                res_json.get("data", {})
                .get("items", [])
            ):

                module_author = (
                    item.get("modules", {})
                    .get("module_author", {})
                )

                if int(
                    module_author.get("mid", 0)
                ) == BILI_UID:

                    try:
                        pub_ts = int(
                            module_author.get(
                                "pub_ts",
                                0
                            )
                        )
                    except:
                        pub_ts = 0

                    if pub_ts > 0:
                        valid_dynamics.append(
                            (pub_ts, item)
                        )

            if not valid_dynamics:
                return

            valid_dynamics.sort(
                key=lambda x: x[0]
            )

            last_saved_time = (
                get_last_saved_time()
            )

            # 初始化锚点
            if last_saved_time == 0:

                max_ts, _ = valid_dynamics[-1]

                save_last_time(max_ts)

                logger.info(
                    f"🎯 初始化动态时间锚点: "
                    f"{max_ts}"
                )

                return

            highest_ts = last_saved_time

            for pub_ts, item in valid_dynamics:

                if pub_ts > last_saved_time:

                    msg_text = parse_single_item(
                        item,
                        pub_ts
                    )

                    if not msg_text:
                        continue

                    bots = get_driver().bots

                    if not bots:
                        logger.warning(
                            "⚠️ 当前没有Bot在线"
                        )
                        return

                    bot = list(
                        bots.values()
                    )[0]

                    # 群推送
                    for group_id in TARGET_GROUP_IDS:

                        try:
                            await bot.send_group_msg(
                                group_id=group_id,
                                message=msg_text
                            )

                            await asyncio.sleep(1.2)

                        except Exception as e:
                            logger.warning(
                                f"群推送失败 "
                                f"{group_id}: {e}"
                            )

                    # 私聊推送
                    for user_id in TARGET_USER_IDS:

                        try:
                            await bot.send_private_msg(
                                user_id=user_id,
                                message=msg_text
                            )

                            await asyncio.sleep(1.2)

                        except Exception as e:
                            logger.warning(
                                f"私聊推送失败 "
                                f"{user_id}: {e}"
                            )

                    if pub_ts > highest_ts:
                        highest_ts = pub_ts

            if highest_ts > last_saved_time:

                save_last_time(highest_ts)

                logger.info(
                    f"✅ 动态时间已更新 "
                    f"{highest_ts}"
                )

    except Exception as e:

        logger.error(
            f"自动监控故障: {e}"
        )


# =========================================================
# 自动轮询
# =========================================================

@scheduler.scheduled_job(
    "interval",
    minutes=CHECK_INTERVAL_MINUTES
)
async def auto_check_job():
    await do_check_logic()


# =========================================================
# Bot上线首发检测
# =========================================================

driver = get_driver()

@driver.on_bot_connect
async def run_safely_when_bot_ready(bot: Bot):

    logger.info(
        f"🎉 Bot {bot.self_id} 已连接"
    )

    await asyncio.sleep(2)

    await do_check_logic(
        is_startup_check=True
    )


# 导入命令模块
from . import commands
