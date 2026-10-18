"""AdminGate: the front door of the admin console, outside every other middleware (CORS too).

For `/api/admin*` it answers before the app does:
- 404 when the console is off (production without ADMIN_HOST), the request came to another
  host than ADMIN_HOST, or the client IP is outside ADMIN_ALLOWED_IPS;
- 403 for requests a page on another origin started (Fetch Metadata `Sec-Fetch-Site` other
  than same-origin / none). SameSite cookies do not cover this: every `*.ai-debates.net` app is
  the same *site* as the console, so a script on any of them could otherwise drive it;
- 403 for unsafe methods without an Origin of the console itself.
On ADMIN_HOST the rest of the API is 404 (the console needs nothing else), and every console
response gets no-store / noindex / no-framing headers. sqladmin's own login page sends the
browser to the console's sign-in page.
"""

from collections.abc import Iterable
from ipaddress import ip_address
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

ADMIN_PREFIX = "/api/admin"
SQLADMIN_PREFIX = "/api/admin/db"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})
OPEN_ON_ADMIN_HOST = frozenset({"/api/health"})
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def is_admin_path(path: str) -> bool:
    return path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/")


def hostname(host_header: str) -> str:
    """Host header without the port, lowercase ("[::1]:80" → "[::1]")."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host.split("]", 1)[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def ip_allowed(client: str | None) -> bool:
    networks = settings.admin_networks
    if not networks:
        return True
    try:
        address = ip_address(client or "")
    except ValueError:
        return False
    return any(address in network for network in networks)


def origin_allowed(origin: str, *, host_header: str, scheme: str) -> bool:
    """The page that sent an unsafe request belongs to the console."""
    parts = urlsplit(origin)
    if not parts.scheme or not parts.netloc:
        return False
    admin_host = settings.admin_hostname
    if admin_host:
        secure_ok = parts.scheme == "https" or not settings.is_production
        return secure_ok and hostname(parts.netloc) == admin_host
    # Development without ADMIN_HOST: the console shares the site's origin (or Vite's).
    return origin in settings.allowed_origins_list or (
        parts.scheme == scheme and parts.netloc.lower() == host_header.strip().lower()
    )


def gate_decision(
    *,
    path: str,
    method: str,
    host_header: str,
    scheme: str,
    client: str | None,
    headers: Headers,
) -> tuple[int, str] | None:
    """(status, message) to refuse a console request with, or None to let it in."""
    if not settings.admin_console_enabled:
        return 404, "Not Found"
    admin_host = settings.admin_hostname
    if admin_host and hostname(host_header) != admin_host:
        return 404, "Not Found"
    if not ip_allowed(client):
        return 404, "Not Found"
    fetch_site = headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in ALLOWED_FETCH_SITES:
        return 403, "Cross-site request refused"
    if method not in SAFE_METHODS:
        origin = headers.get("origin")
        if not origin or not origin_allowed(origin, host_header=host_header, scheme=scheme):
            return 403, "Request from another origin refused"
    return None


def _with_headers(headers: Iterable[tuple[str, str]], response: Response) -> Response:
    for name, value in headers:
        response.headers[name] = value
    return response


class AdminGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        headers = Headers(scope=scope)
        host_header = headers.get("host", "")
        admin_host = settings.admin_hostname
        on_admin_host = bool(admin_host) and hostname(host_header) == admin_host

        if not is_admin_path(path):
            if on_admin_host and path.startswith("/api") and path not in OPEN_ON_ADMIN_HOST:
                await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        client = scope.get("client")
        refusal = gate_decision(
            path=path,
            method=scope["method"],
            host_header=host_header,
            scheme=scope.get("scheme", "http"),
            client=client[0] if client else None,
            headers=headers,
        )
        if refusal is not None:
            status_code, message = refusal
            response = JSONResponse({"detail": message}, status_code=status_code)
            await _with_headers(SECURITY_HEADERS.items(), response)(scope, receive, send)
            return
        if path == f"{SQLADMIN_PREFIX}/login":
            response = RedirectResponse("/admin/login?next=/api/admin/db/", status_code=302)
            await _with_headers(SECURITY_HEADERS.items(), response)(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    response_headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
