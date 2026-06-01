import time
from datetime import datetime

import httpx

from nonebot import on_regex
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
)
from nonebot.exception import FinishedException
from nonebot.log import logger

# Session缓存
DYNAMIC_CACHE_SESSION = {}

# 指令
dynamic_menu_matcher = on_regex(
    r"^(动态)$",
    priority=1,
    block=True
)

update_dynamic_matcher = on_regex(
    r"^(动态刷新|动态更新|刷新动态|更新动态)$",
    priority=1,
    block=True
)

num_select_matcher = on_regex(
    r"^([1-9]|10)$",
    priority=1,
    block=True
)


# =========================================================
# 动态菜单
# =========================================================

@dynamic_menu_matcher.handle()
async def _(bot: Bot, event: GroupMessageEvent):

    user_id = event.user_id
    group_id = event.group_id

    session_key = f"{user_id}_{group_id}"

    from . import (
        BILI_UID,
        get_saved_cookie,
        is_bili_auth_invalid,
        send_bili_login_qrcode_to_admins,
        scan_and_swallow_all_long_strings,
    )

    current_cookie = get_saved_cookie()

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://t.bilibili.com/",
        "Cookie": current_cookie,
    }

    list_url = (
        "https://api.bilibili.com/"
        "x/polymer/web-dynamic/v1/feed/all?type=all"
    )

    try:

        await bot.send(
            event,
            "🔄 正在拉取B站动态..."
        )

        async with httpx.AsyncClient(
            headers=headers,
            timeout=10.0,
            follow_redirects=True
        ) as client:

            response = await client.get(list_url)
            res_json = response.json()

            if is_bili_auth_invalid(
                response.status_code,
                res_json
            ):
                await send_bili_login_qrcode_to_admins(
                    "用户查询动态时发现B站登录失效"
                )

                await dynamic_menu_matcher.finish(
                    "⚠️ Cookie已失效。"
                )

            items = (
                res_json.get("data", {})
                .get("items", [])
            )

            if not items:
                await dynamic_menu_matcher.finish(
                    "📭 没有动态数据。"
                )

            target_dynamics = []

            for item in items:

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
                        target_dynamics.append(
                            (pub_ts, item)
                        )

            if not target_dynamics:
                await dynamic_menu_matcher.finish(
                    "📭 近期没有公开动态。"
                )

            target_dynamics.sort(
                key=lambda x: x[0],
                reverse=True
            )

            menu_list = target_dynamics[:10]

            reply_text = (
                "📋 【最新动态列表】\n"
                "👉 发送数字查看详情\n"
                "-------------------------\n"
            )

            cached_items_queue = []

            for index, (
                pub_ts,
                item
            ) in enumerate(
                menu_list,
                start=1
            ):

                time_str = datetime.fromtimestamp(
                    pub_ts
                ).strftime("%Y-%m-%d %H:%M:%S")

                all_words = (
                    scan_and_swallow_all_long_strings(
                        item
                    )
                )

                brief = (
                    all_words[0][:12] + "..."
                    if all_words
                    else "赛尔号发布了一条动态"
                )

                reply_text += (
                    f"【{index}】 "
                    f"⏰ {time_str}\n"
                    f"📝 {brief}\n"
                )

                cached_items_queue.append(item)

            reply_text += (
                "-------------------------\n"
                "💡 三分钟内有效"
            )

            DYNAMIC_CACHE_SESSION[
                session_key
            ] = {
                "expire": time.time() + 180,
                "items": cached_items_queue,
            }

            logger.info(
                f"📋 用户 {user_id} 获取动态菜单成功"
            )

            await dynamic_menu_matcher.finish(
                Message(reply_text)
            )

    except FinishedException:
        raise

    except Exception as e:

        logger.error(
            f"动态菜单故障: {e}"
        )

        await dynamic_menu_matcher.finish(
            "❌ 获取动态列表失败。"
        )


# =========================================================
# 管理员更新动态
# =========================================================

@update_dynamic_matcher.handle()
async def _(bot: Bot, event: GroupMessageEvent):

    user_id = event.user_id

    from . import is_bili_admin

    if not is_bili_admin(user_id):

        await update_dynamic_matcher.finish(
            "⛔ 仅超级管理员可用。"
        )

    from . import do_check_logic

    try:

        logger.info(
            f"⚡ 管理员 {user_id} 手动更新动态"
        )

        await bot.send(
            event,
            "⚡ 正在刷新动态..."
        )

        await do_check_logic(
            is_startup_check=True
        )

        await update_dynamic_matcher.finish(
            "✅ 动态刷新完成。"
        )

    except FinishedException:
        raise

    except Exception as e:

        logger.error(
            f"手动更新动态故障: {e}"
        )

        await update_dynamic_matcher.finish(
            "❌ 动态刷新失败。"
        )


# =========================================================
# 数字详情
# =========================================================

@num_select_matcher.handle()
async def _(bot: Bot, event: GroupMessageEvent):

    user_id = event.user_id
    group_id = event.group_id

    session_key = f"{user_id}_{group_id}"

    if session_key not in DYNAMIC_CACHE_SESSION:
        return

    session_data = DYNAMIC_CACHE_SESSION[
        session_key
    ]

    if time.time() > session_data["expire"]:

        del DYNAMIC_CACHE_SESSION[
            session_key
        ]

        await num_select_matcher.finish(
            "⏳ 会话已超时，请重新发送“动态”。"
        )

    try:

        from . import parse_single_item

        raw_msg = (
            event.get_plaintext()
            .strip()
        )

        select_num = int(raw_msg)

        cached_items = session_data["items"]

        if (
            select_num < 1
            or select_num > len(cached_items)
        ):
            return

        target_item = cached_items[
            select_num - 1
        ]

        pub_ts = int(
            target_item.get(
                "modules",
                {}
            ).get(
                "module_author",
                {}
            ).get(
                "pub_ts",
                0
            )
        )

        final_message = parse_single_item(
            target_item,
            pub_ts,
            menu_mode=True
        )

        del DYNAMIC_CACHE_SESSION[
            session_key
        ]

        if final_message:

            await num_select_matcher.finish(
                Message(final_message)
            )

    except FinishedException:
        raise

    except Exception as e:

        logger.error(
            f"数字点播故障: {e}"
        )

        await num_select_matcher.finish(
            "❌ 动态详情解析失败。"
        )
