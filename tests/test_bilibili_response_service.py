from ironsbot.services.bilibili.responses import check_dynamic_response

HTTP_OK = 200
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_UNAVAILABLE = 503
API_OK = 0
API_AUTH_INVALID = -101
API_RATE_LIMITED = 412
API_ERROR = -400


def test_check_dynamic_response_accepts_success() -> None:
    result = check_dynamic_response(HTTP_OK, {"code": API_OK})

    assert result.is_ok
    assert result.status == "ok"
    assert result.http_status == HTTP_OK
    assert result.api_code == API_OK


def test_check_dynamic_response_detects_auth_invalid() -> None:
    assert (
        check_dynamic_response(HTTP_UNAUTHORIZED, {"code": API_OK}).status
        == "auth_invalid"
    )
    assert (
        check_dynamic_response(HTTP_FORBIDDEN, {"code": API_OK}).status
        == "auth_invalid"
    )
    assert (
        check_dynamic_response(HTTP_OK, {"code": API_AUTH_INVALID}).status
        == "auth_invalid"
    )
    assert (
        check_dynamic_response(HTTP_OK, {"code": API_RATE_LIMITED}).status
        == "auth_invalid"
    )


def test_check_dynamic_response_reports_http_error() -> None:
    result = check_dynamic_response(HTTP_UNAVAILABLE, {"code": API_OK})

    assert result.status == "http_error"
    assert result.http_status == HTTP_UNAVAILABLE
    assert result.api_code == API_OK


def test_check_dynamic_response_reports_api_error() -> None:
    result = check_dynamic_response(HTTP_OK, {"code": API_ERROR})

    assert result.status == "api_error"
    assert result.http_status == HTTP_OK
    assert result.api_code == API_ERROR
