"""The layer as an HTTP service, for a company that runs it in its own network.

    pip install "antihallucination[server]"
    ANTIHALLUCINATION_TOKEN=<a long random string> antihallucination serve --host 0.0.0.0

One process serves two doors to the same four checks as the stdio MCP server:

    POST /v1/prepare   {"brief", "data", "locale"}              → prepare_report
    POST /v1/compose   {"draft", "data", "locale", "writer"}    → compose_report
    POST /v1/verify    {"text", "data", "locale", "writer"}     → verify_text
    POST /v1/receipt   {"receipt", "data"}                      → check_receipt
    /mcp               the same tools for an MCP client, over HTTP
    GET  /health       {"status": "ok", "version": ...}, the only route without the token

"data" is the JSON the command line reads (antihallucination/data.py); its
"locale" is the default when the request gives none. "writer" names who wrote
the text, for the receipt. Like the stdio server, the service calls no model:
nobody who reaches it can spend a provider's tokens, and nothing leaves it.

With a token, every route but /health needs `Authorization: Bearer <token>`.
A request body over max_body bytes is refused before it is read in full.
"""

import hmac
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal

import uvicorn
from mcp.server.mcpserver.exceptions import ToolError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .mcp_server import run_check_receipt, run_compose, run_prepare, run_verify, server

# The checks grow in line with the text (tests/test_long_texts.py holds them
# to it): 256 KB of ordinary text, about 5,000 sentences, takes 0.7 s on one
# core, and the slowest text known, 2.5 s.
DEFAULT_MAX_BODY = 262_144
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

Body = Mapping[str, object]


class _BadRequest(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _fields(body: Body, required: Sequence[str], optional: Sequence[str] = ()) -> None:
    unknown = set(body) - set(required) - set(optional)
    if unknown:
        raise _BadRequest(f"unknown keys: {', '.join(sorted(unknown))}")
    missing = [key for key in required if key not in body]
    if missing:
        raise _BadRequest(f"missing keys: {', '.join(missing)}")


def _text(body: Body, key: str, default: str = "") -> str:
    value = body.get(key, default)
    if not isinstance(value, str):
        raise _BadRequest(f"{key} must be text")
    return value


def _object(body: Body, key: str) -> Body | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _BadRequest(f"{key} must be a JSON object")
    return {str(name): item for name, item in value.items()}


def _data(body: Body) -> Body:
    return _object(body, "data") or {}


def _locale(body: Body, data: Body, allowed: Sequence[str], default: str) -> str:
    """The request's locale, else the data file's, else the default."""
    value = body.get("locale", data.get("locale", default))
    if value not in allowed:
        raise _BadRequest(f"locale must be one of: {', '.join(allowed)}")
    return str(value)


def _prepare(body: Body) -> object:
    _fields(body, ("brief", "data"), ("locale",))
    data = _data(body)
    return run_prepare(_text(body, "brief"), data, _locale(body, data, ("es", "en"), "en"))


def _compose(body: Body) -> object:
    _fields(body, ("draft", "data"), ("locale", "writer"))
    data = _data(body)
    locale = _locale(body, data, ("es", "en"), "en")
    return run_compose(_text(body, "draft"), data, locale, writer=_text(body, "writer", "http client"))


def _verify(body: Body) -> object:
    _fields(body, ("text", "data"), ("locale", "writer"))
    data = _data(body)
    locale = _locale(body, data, ("es", "en", "auto"), "auto")
    return run_verify(_text(body, "text"), data, locale, writer=_text(body, "writer"))


def _receipt(body: Body) -> object:
    _fields(body, ("receipt",), ("data",))
    return run_check_receipt(_object(body, "receipt") or {}, _object(body, "data"))


async def _payload(request: Request) -> Body:
    """The request's JSON object, read up to the size limit; numbers as exact decimals."""
    limit: int = request.app.state.max_body
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _BadRequest(f"the body is over the limit of {limit} bytes", 413)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _BadRequest(f"the body is over the limit of {limit} bytes", 413)
        chunks.append(chunk)
    try:
        body: object = json.loads(b"".join(chunks), parse_float=Decimal)
    except ValueError as exc:
        raise _BadRequest(f"the body is not valid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise _BadRequest("the body must be a JSON object")
    return {str(key): value for key, value in body.items()}


def _endpoint(handler: Callable[[Body], object]) -> Callable[[Request], Awaitable[Response]]:
    async def endpoint(request: Request) -> Response:
        try:
            body = await _payload(request)
            # The checks are plain CPU work: off the event loop, so /health and
            # other requests still answer while a long text is being checked.
            result = await run_in_threadpool(handler, body)
        except _BadRequest as exc:
            return JSONResponse({"error": exc.message}, status_code=exc.status)
        except ToolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result)

    return endpoint


async def _health(request: Request) -> Response:
    return JSONResponse({"status": "ok", "version": __version__})


class TokenGate:
    """Lets a request through only with `Authorization: Bearer <token>`; /health is open.

    A plain ASGI wrapper, not Starlette's BaseHTTPMiddleware, so the MCP
    route's streamed responses pass through untouched.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = b"Bearer " + token.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] != "/health":
            given = b""
            for name, value in scope["headers"]:
                if name == b"authorization":
                    given = value
            if not hmac.compare_digest(given, self.expected):
                refusal = JSONResponse(
                    {"error": "this service needs its token: send Authorization: Bearer <token>"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await refusal(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(*, token: str | None, max_body: int = DEFAULT_MAX_BODY, host: str = "127.0.0.1") -> ASGIApp:
    """The service as an ASGI app: the REST routes and /mcp, behind the token if there is one.

    host is where it will listen. On this machine only (127.0.0.1), the MCP
    route also refuses requests whose Host header is not local, against DNS
    rebinding from a web page.
    """
    if max_body < 1:
        raise ValueError("max_body must be at least 1 byte")
    # Stateless and plain JSON: any instance behind a load balancer can answer
    # any request, and no proxy has to keep a stream open.
    app = server.streamable_http_app(
        stateless_http=True, json_response=True, max_request_body_size=max_body, host=host
    )
    app.state.max_body = max_body
    app.router.routes.extend(
        [
            Route("/health", _health, methods=["GET"]),
            Route("/v1/prepare", _endpoint(_prepare), methods=["POST"]),
            Route("/v1/compose", _endpoint(_compose), methods=["POST"]),
            Route("/v1/verify", _endpoint(_verify), methods=["POST"]),
            Route("/v1/receipt", _endpoint(_receipt), methods=["POST"]),
        ]
    )
    return TokenGate(app, token) if token else app


def serve(*, host: str, port: int, token: str | None, max_body: int = DEFAULT_MAX_BODY) -> None:
    """Run the service until it is stopped."""
    uvicorn.run(create_app(token=token, max_body=max_body, host=host), host=host, port=port, server_header=False)
