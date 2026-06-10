import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, Literal

from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.log import logger

MIN_DYNAMIC_TEXT_LENGTH = 15
MAX_DYNAMIC_CONTENT_CHARS = 500
DynamicRenderMode = Literal["full", "link"]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _module_author(item: dict[str, Any]) -> Mapping[str, Any]:
    modules = _mapping(item.get("modules"))
    return _mapping(modules.get("module_author"))


def item_pub_ts(item: dict[str, Any]) -> int:
    try:
        return int(_module_author(item).get("pub_ts", 0))
    except (TypeError, ValueError):
        return 0


def item_author_mid(item: dict[str, Any]) -> int:
    try:
        return int(_module_author(item).get("mid", 0))
    except (TypeError, ValueError):
        return 0


def item_author_name(item: dict[str, Any]) -> str:
    module_author = _module_author(item)
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


def dynamic_id(item: dict[str, Any]) -> str:
    return str(item.get("id_str") or item.get("id") or "")


def dynamic_url(item: dict[str, Any]) -> str:
    item_id = dynamic_id(item)
    return f"https://t.bilibili.com/{item_id}" if item_id else "https://t.bilibili.com/"


def find_target_dynamics(
    items: list[dict[str, Any]],
    target_uids: Iterable[int],
) -> list[tuple[int, dict[str, Any]]]:
    target_dynamics: list[tuple[int, dict[str, Any]]] = []
    uid_set = {int(uid) for uid in target_uids if int(uid) > 0}
    if not uid_set:
        return target_dynamics

    for item in items:
        if item_author_mid(item) not in uid_set:
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
                    len(text) >= MIN_DYNAMIC_TEXT_LENGTH
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


def _append_unique_piece(pieces: list[str], piece: str) -> None:
    if any(piece == old_piece or piece in old_piece for old_piece in pieces):
        return

    pieces[:] = [old_piece for old_piece in pieces if old_piece not in piece]
    pieces.append(piece)


def dynamic_text_pieces(item: dict[str, Any]) -> list[str]:
    unique_pieces: list[str] = []
    for raw_piece in scan_and_swallow_all_long_strings(item):
        piece = raw_piece.strip()
        if piece:
            _append_unique_piece(unique_pieces, piece)
    return unique_pieces


def dynamic_content(item: dict[str, Any]) -> str:
    content = "\n".join(dynamic_text_pieces(item)).strip()
    if content:
        return content
    return f"{item_author_name(item)}发布了一条动态\n回复“动态”查询历史动态"


def dynamic_brief(item: dict[str, Any]) -> str:
    pieces = dynamic_text_pieces(item)
    if pieces:
        return pieces[0][:18] + "..."

    return f"{item_author_name(item)}发布了一条动态"


def dynamic_suppression_reason(
    item: dict[str, Any],
    patterns: list[str],
) -> str:
    content = dynamic_content(item)
    for pattern in patterns:
        try:
            regex = re.compile(pattern, flags=re.IGNORECASE | re.DOTALL)
        except re.error as e:
            logger.warning(f"invalid Bilibili suppress pattern {pattern!r}: {e}")
            continue

        if regex.search(content):
            return f"命中规则：{pattern}"
    return ""


def _image_urls(item: dict[str, Any]) -> list[str]:
    image_urls: list[str] = []
    module_dynamic = _mapping(_mapping(item.get("modules")).get("module_dynamic"))
    major = _mapping(module_dynamic.get("major"))

    if "draw" in major:
        image_urls.extend(
            pic["src"]
            for pic in _mapping(major.get("draw")).get("items", [])
            if isinstance(pic, Mapping) and pic.get("src")
        )
    elif "opus" in major:
        image_urls.extend(
            pic["url"]
            for pic in _mapping(major.get("opus")).get("pics", [])
            if isinstance(pic, Mapping) and pic.get("url")
        )
    elif "archive" in major:
        cover = _mapping(major.get("archive")).get("cover")
        if cover:
            image_urls.append(str(cover))

    return image_urls


def parse_single_item(
    item: dict[str, Any],
    pub_ts: int,
    *,
    menu_mode: bool = False,
    mode: DynamicRenderMode = "full",
) -> Message | None:
    try:
        time_str = datetime.fromtimestamp(
            pub_ts,
            tz=timezone.utc,
        ).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        author_label = item_author_label(item)
        tag = "B站点播详情" if menu_mode else "B站动态更新"
        url = dynamic_url(item)

        message = Message()
        message += MessageSegment.text(
            f"🔔 【{tag}】\n"
            f"👤 账号：{author_label}\n"
            f"⏰ 发布时间: {time_str}\n\n"
        )

        if mode == "full":
            content = dynamic_content(item)
            short_content = (
                content[:MAX_DYNAMIC_CONTENT_CHARS] + "..."
                if len(content) > MAX_DYNAMIC_CONTENT_CHARS
                else content
            )
            message += MessageSegment.text(f"{short_content}\n")

            for image_url in _image_urls(item):
                sanitized_url = image_url.strip().rstrip("]")
                if sanitized_url:
                    message += MessageSegment.image(sanitized_url)
                    message += MessageSegment.text("\n")

        message += MessageSegment.text(f"传送门: {url}")

    except (TypeError, ValueError, KeyError) as e:
        logger.error(f"failed to parse Bilibili dynamic: {e}")
        return None

    return message
