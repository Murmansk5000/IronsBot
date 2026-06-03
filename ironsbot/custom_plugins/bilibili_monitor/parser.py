import re
from datetime import datetime
from typing import Any

from nonebot.log import logger

from .state import BILI_UIDS


def item_pub_ts(item: dict[str, Any]) -> int:
    try:
        return int(
            item.get("modules", {})
            .get("module_author", {})
            .get("pub_ts", 0)
        )
    except Exception:
        return 0


def item_author_mid(item: dict[str, Any]) -> int:
    module_author = item.get("modules", {}).get("module_author", {})
    try:
        return int(module_author.get("mid", 0))
    except Exception:
        return 0


def item_author_name(item: dict[str, Any]) -> str:
    module_author = item.get("modules", {}).get("module_author", {})
    for key in ("name", "uname"):
        name = str(module_author.get(key) or "").strip()
        if name:
            return name

    author_mid = item_author_mid(item)
    if author_mid:
        return f"UID {author_mid}"

    return "该账号"


def item_author_label(item: dict[str, Any]) -> str:
    author_name = item_author_name(item)
    author_mid = item_author_mid(item)
    if author_mid and not author_name.startswith("UID "):
        return f"{author_name}（UID：{author_mid}）"

    return author_name


def find_target_dynamics(items: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    target_dynamics: list[tuple[int, dict[str, Any]]] = []
    target_uids = set(BILI_UIDS)

    for item in items:
        if item_author_mid(item) not in target_uids:
            continue

        pub_ts = item_pub_ts(item)
        if pub_ts > 0:
            target_dynamics.append((pub_ts, item))

    return target_dynamics


def scan_and_swallow_all_long_strings(data_obj: Any) -> list[str]:
    texts: list[str] = []
    ignore_keys = {
        "url",
        "src",
        "jump_url",
        "cover",
        "face",
        "card_url",
        "avatar",
        "uri",
    }

    if isinstance(data_obj, dict):
        for key, value in data_obj.items():
            if key in ignore_keys:
                continue

            if isinstance(value, str):
                text = value.strip()
                if (
                    len(text) >= 15
                    and re.search(r"[\u4e00-\u9fa5]", text)
                    and "取消关注" not in text
                    and "举报" not in text
                    and "AUTHOR_TYPE" not in text
                ):
                    texts.append(text)
            else:
                texts.extend(scan_and_swallow_all_long_strings(value))

    elif isinstance(data_obj, list):
        for item in data_obj:
            texts.extend(scan_and_swallow_all_long_strings(item))

    return texts


def dynamic_brief(item: dict[str, Any]) -> str:
    texts = scan_and_swallow_all_long_strings(item)
    if texts:
        return texts[0][:18] + "..."

    return f"{item_author_name(item)}发布了一条动态"


def _image_urls(item: dict[str, Any]) -> list[str]:
    image_urls: list[str] = []
    module_dynamic = (item.get("modules") or {}).get("module_dynamic") or {}
    major = module_dynamic.get("major") or {}

    if "draw" in major:
        for pic in (major.get("draw") or {}).get("items", []):
            if pic.get("src"):
                image_urls.append(pic["src"])
    elif "opus" in major:
        for pic in (major.get("opus") or {}).get("pics", []):
            if pic.get("url"):
                image_urls.append(pic["url"])
    elif "archive" in major:
        cover = (major.get("archive") or {}).get("cover")
        if cover:
            image_urls.append(cover)

    return image_urls


def parse_single_item(
    item: dict[str, Any],
    pub_ts: int,
    menu_mode: bool = False,
) -> str | None:
    try:
        dynamic_id = str(item.get("id_str") or "")
        time_str = datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M:%S")
        author_label = item_author_label(item)

        unique_pieces: list[str] = []
        for piece in scan_and_swallow_all_long_strings(item):
            piece = piece.strip()
            if piece and piece not in unique_pieces:
                unique_pieces.append(piece)

        content = "\n".join(unique_pieces).strip()
        if not content:
            content = f"{item_author_name(item)}发布了一条动态\n回复“动态”查询历史动态"

        cq_images = "".join(
            f"\n[CQ:image,file={image_url}]"
            for image_url in _image_urls(item)
        )
        short_content = content[:500] + "..." if len(content) > 500 else content
        tag = "点播详情" if menu_mode else "动态更新"

        return (
            f"🔔 【B站{tag}】\n"
            f"👤 账号：{author_label}\n"
            f"⏰ 发布时间: {time_str}\n\n"
            f"{short_content}"
            f"{cq_images}\n\n"
            f"传送门: https://t.bilibili.com/{dynamic_id}"
        )

    except Exception as e:
        logger.error(f"failed to parse Bilibili dynamic: {e}")
        return None
