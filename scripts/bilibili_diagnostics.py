# ruff: noqa: T201, TRY003
"""Local-only Bilibili login and recent-dynamic body diagnostics.

The saved cookie lives under data/ (which is ignored by Git) and is never read
by the production Bilibili service.  Do not copy it to deployment hosts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ironsbot.integrations.http.bilibili import (
    fetch_bili_dynamic_detail,
    fetch_bili_space_feed,
    poll_bili_login_qr,
    request_bili_login_qr,
)
from ironsbot.integrations.storage.bilibili_cookie import (
    FileBiliCookieStore,
)
from ironsbot.services.bilibili.auth import (
    build_bili_login_qrcode_message_parts,
    extract_bili_login_cookie,
)
from ironsbot.services.bilibili.hydration import hydrate_dynamic_item
from ironsbot.services.bilibili.parser import (
    dynamic_content,
    dynamic_id,
    item_pub_ts,
)

DEFAULT_UID = 1310714247
DEFAULT_COOKIE_PATH = PROJECT_ROOT / "data" / "diagnostics" / "bilibili_cookie.txt"
DEFAULT_QR_PATH = PROJECT_ROOT / "data" / "diagnostics" / "bilibili_login_qr.png"
DEFAULT_LOGIN_STATE_PATH = (
    PROJECT_ROOT / "data" / "diagnostics" / "bilibili_login_state.json"
)
HTTP_OK = 200
QR_EXPIRED_CODE = 86038


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cookie-path",
        type=Path,
        default=DEFAULT_COOKIE_PATH,
        help="Local ignored Cookie path used only by this script.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("login", help="Create a QR login and save its Cookie.")
    subcommands.add_parser("login-start", help="Create a QR for a two-step login.")
    subcommands.add_parser("login-poll", help="Save Cookie after scanning login-start.")
    week = subcommands.add_parser("check-week", help="Inspect recent dynamic bodies.")
    week.add_argument("--uid", type=int, default=DEFAULT_UID)
    week.add_argument("--days", type=int, default=7)
    return parser.parse_args()


def _save_qr_image(url: str) -> None:
    parts = build_bili_login_qrcode_message_parts(url)
    if not parts.image_base64:
        raise RuntimeError(parts.image_error or "Failed to build Bilibili QR image")
    import base64

    DEFAULT_QR_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_QR_PATH.write_bytes(base64.b64decode(parts.image_base64))


def _save_login_state(qrcode_key: str) -> None:
    DEFAULT_LOGIN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_LOGIN_STATE_PATH.write_text(
        json.dumps({"qrcode_key": qrcode_key}),
        encoding="utf-8",
    )


def _load_login_state() -> str:
    try:
        state = json.loads(DEFAULT_LOGIN_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "No saved Bilibili QR session; run login-start first"
        ) from error
    qrcode_key = str(state.get("qrcode_key") or "").strip()
    if not qrcode_key:
        raise RuntimeError(
            "Saved Bilibili QR session is invalid; run login-start again"
        )
    return qrcode_key


def _save_login_cookie(
    cookie_path: Path,
    *,
    cookies: dict[str, str],
    login_url: str,
) -> None:
    cookie = extract_bili_login_cookie(cookies, login_url)
    if "SESSDATA=" not in cookie:
        raise RuntimeError("Bilibili login did not return SESSDATA")
    FileBiliCookieStore(cookie_path).save(cookie)
    DEFAULT_LOGIN_STATE_PATH.unlink(missing_ok=True)
    print(f"Local development Cookie saved: {cookie_path}")


async def _login_start() -> None:
    async with httpx.AsyncClient() as client:
        request = await request_bili_login_qr(client)
    _save_qr_image(request.url)
    _save_login_state(request.qrcode_key)
    print(f"Scan this QR in Bilibili: {DEFAULT_QR_PATH}")


async def _login_poll(cookie_path: Path) -> bool:
    qrcode_key = _load_login_state()
    async with httpx.AsyncClient() as client:
        result = await poll_bili_login_qr(client, qrcode_key)
    if result.code == 0:
        _save_login_cookie(
            cookie_path,
            cookies=result.cookies,
            login_url=result.login_url,
        )
        return True
    if result.code == QR_EXPIRED_CODE:
        DEFAULT_LOGIN_STATE_PATH.unlink(missing_ok=True)
        raise RuntimeError("Bilibili QR expired before login confirmation")
    print("Bilibili QR has not been confirmed yet.")
    return False


async def _login(cookie_path: Path) -> None:
    await _login_start()
    for _ in range(36):
        await asyncio.sleep(5)
        if await _login_poll(cookie_path):
            return
    raise RuntimeError("Bilibili QR expired before login confirmation")


def _items(payload: object) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    raw_items = data.get("items") if isinstance(data, dict) else None
    return [item for item in raw_items or [] if isinstance(item, dict)]


def _next_offset(payload: object) -> str:
    data = payload.get("data") if isinstance(payload, dict) else None
    return str(data.get("offset") or "") if isinstance(data, dict) else ""


async def _check_week(cookie_path: Path, *, uid: int, days: int) -> None:
    cookie = FileBiliCookieStore(cookie_path).load()
    if not cookie:
        raise RuntimeError(f"No test Cookie found at {cookie_path}; run login first")
    cutoff = int(
        (datetime.now(timezone.utc) - timedelta(days=max(days, 0))).timestamp()
    )
    all_items: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        offset = ""
        for _ in range(10):
            response = await fetch_bili_space_feed(client, cookie, uid, offset)
            payload = response.data if isinstance(response.data, dict) else {}
            if response.status_code != HTTP_OK or payload.get("code") != 0:
                raise RuntimeError(
                    "Space feed failed: "
                    f"HTTP={response.status_code} code={payload.get('code')}"
                )
            items = _items(payload)
            if not items:
                break
            all_items.extend(items)
            if min((item_pub_ts(item) for item in items), default=0) < cutoff:
                break
            next_offset = _next_offset(payload)
            if not next_offset or next_offset == offset:
                break
            offset = next_offset

        recent = [item for item in all_items if item_pub_ts(item) >= cutoff]
        resolved_count = 0
        for item in recent:
            before = dynamic_content(item)
            resolved = await hydrate_dynamic_item(
                item,
                cookie=cookie,
                fetch_detail=lambda saved_cookie, dynamic: fetch_bili_dynamic_detail(
                    client,
                    saved_cookie,
                    dynamic,
                ),
            )
            after = dynamic_content(resolved)
            resolved_count += int(not before and bool(after))
            published = datetime.fromtimestamp(
                item_pub_ts(item), tz=timezone.utc
            ).astimezone().isoformat()
            print(
                f"{published} id={dynamic_id(item)} "
                f"feed_chars={len(before)} resolved_chars={len(after)}"
            )
    print(f"Checked {len(recent)} dynamics; detail-resolved {resolved_count}.")


async def _main() -> None:
    args = _parse_args()
    if args.command == "login":
        await _login(args.cookie_path)
        return
    if args.command == "login-start":
        await _login_start()
        return
    if args.command == "login-poll":
        await _login_poll(args.cookie_path)
        return
    await _check_week(args.cookie_path, uid=args.uid, days=args.days)


if __name__ == "__main__":
    asyncio.run(_main())
