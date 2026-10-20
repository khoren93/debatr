from starlette.requests import Request

from app.services.views import RENDER_HEADER, counts_as_view


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


def test_the_page_renderer_is_not_a_view() -> None:
    assert counts_as_view(_request({})) is True
    assert counts_as_view(_request({"user-agent": "Mozilla/5.0"})) is True
    assert counts_as_view(_request({RENDER_HEADER: "server"})) is False
    assert counts_as_view(_request({RENDER_HEADER: "something else"})) is True
