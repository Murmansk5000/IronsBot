import httpx

LIST_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?type=all"


def bili_headers(cookie: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://t.bilibili.com/",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def fetch_dynamic_feed(
    cookie: str,
) -> tuple[httpx.Response, dict]:
    async with httpx.AsyncClient(
        headers=bili_headers(cookie),
        timeout=10.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(LIST_URL)

    return response, response.json()
