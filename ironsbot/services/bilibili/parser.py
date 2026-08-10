import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

MIN_DYNAMIC_TEXT_LENGTH = 15
logger = logging.getLogger(__name__)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _module_author(item: dict[str, Any]) -> Mapping[str, Any]:
    modules = _mapping(item.get("modules"))
    return _mapping(modules.get("module_author"))


def _module_dynamic(item: dict[str, Any]) -> Mapping[str, Any]:
    modules = _mapping(item.get("modules"))
    return _mapping(modules.get("module_dynamic"))


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


def dynamic_items_from_response(response_data: object) -> list[dict[str, Any]]:
    payload = _mapping(_mapping(response_data).get("data"))
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    return [item for item in items if isinstance(item, dict)]


def target_dynamics_from_response(
    response_data: object,
    target_uids: Iterable[int],
    *,
    newest_first: bool = False,
) -> list[tuple[int, dict[str, Any]]]:
    target_dynamics = find_target_dynamics(
        dynamic_items_from_response(response_data),
        target_uids,
    )
    target_dynamics.sort(key=lambda value: value[0], reverse=newest_first)
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


def _text_value(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Mapping):
        return str(value.get("text") or "").strip()
    return ""


def _topic_name(item: dict[str, Any]) -> str:
    topic = _mapping(_module_dynamic(item).get("topic"))
    return str(topic.get("name") or "").strip()


def _structured_dynamic_text_pieces(item: dict[str, Any]) -> list[str]:
    dynamic = _module_dynamic(item)
    major = _mapping(dynamic.get("major"))
    opus = _mapping(major.get("opus"))
    archive = _mapping(major.get("archive"))
    pieces = [
        _text_value(opus.get("summary")),
        _text_value(dynamic.get("desc")),
        _text_value(archive.get("desc")),
    ]
    return [piece for piece in pieces if piece]


def dynamic_text_pieces(item: dict[str, Any]) -> list[str]:
    unique_pieces: list[str] = []
    structured_pieces = _structured_dynamic_text_pieces(item)
    raw_pieces = structured_pieces or scan_and_swallow_all_long_strings(
        _module_dynamic(item)
    )
    for raw_piece in raw_pieces:
        piece = raw_piece.strip()
        if piece:
            _append_unique_piece(unique_pieces, piece)
    return unique_pieces


def dynamic_content(item: dict[str, Any]) -> str:
    """Return only text actually present in the dynamic itself."""

    return "\n".join(dynamic_text_pieces(item)).strip()


def dynamic_classification_text(item: dict[str, Any]) -> str:
    """Return dynamic body plus short semantic fields used only for matching."""

    pieces = dynamic_text_pieces(item)
    topic = _topic_name(item)
    if topic:
        _append_unique_piece(pieces, topic)
    return "\n".join(pieces).strip()


def has_dynamic_body(item: dict[str, Any]) -> bool:
    """Whether an item has actual post text rather than author metadata."""

    return bool(dynamic_text_pieces(item))


def dynamic_brief(item: dict[str, Any]) -> str:
    pieces = dynamic_text_pieces(item)
    if pieces:
        return pieces[0][:18] + "..."

    return f"{item_author_name(item)}发布了一条动态"


def dynamic_suppression_reason(
    item: dict[str, Any],
    patterns: list[str],
) -> str:
    content = dynamic_classification_text(item)
    for pattern in patterns:
        try:
            regex = re.compile(pattern, flags=re.IGNORECASE | re.DOTALL)
        except re.error as e:
            logger.warning(f"invalid Bilibili suppress pattern {pattern!r}: {e}")
            continue

        if regex.search(content):
            return f"命中规则：{pattern}"
    return ""


def dynamic_image_urls(item: dict[str, Any]) -> list[str]:
    module_dynamic = _mapping(_mapping(item.get("modules")).get("module_dynamic"))
    major = _mapping(module_dynamic.get("major"))

    draw_urls = [
        str(pic["src"])
        for pic in _mapping(major.get("draw")).get("items", [])
        if isinstance(pic, Mapping) and pic.get("src")
    ]
    if draw_urls:
        return draw_urls

    opus_urls = [
        str(pic["url"])
        for pic in _mapping(major.get("opus")).get("pics", [])
        if isinstance(pic, Mapping) and pic.get("url")
    ]
    if opus_urls:
        return opus_urls

    cover = _mapping(major.get("archive")).get("cover")
    return [str(cover)] if cover else []
