from dataclasses import dataclass
from typing import Literal

from ironsbot.services.bilibili.auth import is_bili_auth_invalid

HTTP_OK = 200
BILI_API_OK = 0

DynamicResponseStatus = Literal[
    "ok",
    "auth_invalid",
    "http_error",
    "api_error",
]


@dataclass(frozen=True, slots=True)
class DynamicResponseCheck:
    status: DynamicResponseStatus
    http_status: int
    api_code: object | None = None

    @property
    def is_ok(self) -> bool:
        return self.status == "ok"


def check_dynamic_response(
    status_code: int,
    data: object,
) -> DynamicResponseCheck:
    response_data = data if isinstance(data, dict) else None
    api_code = response_data.get("code") if response_data is not None else None

    if is_bili_auth_invalid(status_code, response_data):
        return DynamicResponseCheck(
            status="auth_invalid",
            http_status=status_code,
            api_code=api_code,
        )

    if status_code != HTTP_OK:
        return DynamicResponseCheck(
            status="http_error",
            http_status=status_code,
            api_code=api_code,
        )

    if api_code != BILI_API_OK:
        return DynamicResponseCheck(
            status="api_error",
            http_status=status_code,
            api_code=api_code,
        )

    return DynamicResponseCheck(
        status="ok",
        http_status=status_code,
        api_code=api_code,
    )
