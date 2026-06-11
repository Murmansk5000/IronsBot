from urllib.parse import parse_qsl, urlparse

import httpx

AUTH_INVALID_CODES = {-101, -401, -403, 412}
LOGIN_QR_EXPIRE_SECONDS = 180
LOGIN_COOKIE_KEYS = {
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
}


def is_bili_auth_invalid(
    status_code: int,
    data: dict | None = None,
) -> bool:
    if status_code in {401, 403}:
        return True

    if not isinstance(data, dict):
        return False

    return data.get("code") in AUTH_INVALID_CODES


def extract_bili_login_cookie(
    response: httpx.Response,
    login_url: str = "",
) -> str:
    cookies: dict[str, str] = {
        key: value
        for key, value in response.cookies.items()
        if value
    }

    if login_url:
        query_items = parse_qsl(
            urlparse(login_url).query,
            keep_blank_values=False,
        )
        cookies.update(
            {
                key: value
                for key, value in query_items
                if key in LOGIN_COOKIE_KEYS and value
            }
        )

    return "; ".join(f"{key}={value}" for key, value in cookies.items())

