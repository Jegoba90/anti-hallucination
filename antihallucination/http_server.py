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
A POST must say `Content-Type: application/json`. Listening on this machine
only, the service also refuses a Host or Origin header that is not local, as
the MCP route does, against DNS rebinding from a web page.
A request body over max_body bytes is refused before it is read in full. Each
request's checks run in a worker process with a time limit and, on Linux and
macOS, a memory limit: past either, the answer is 413 and the service goes on.
"""

import hmac
import json
import math
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from decimal import Decimal
from functools import partial
from typing import TypeVar

import anyio
import anyio.to_process
import uvicorn
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .mcp_server import TooMuchWork, build_server, run_check_receipt, run_compose, run_prepare, run_verify
from .worker import TIMES_ITSELF, run_capped

# The checks grow in line with the text and the data (tests/test_long_texts.py
# and tests/test_large_data.py hold them to it): 256 KB of ordinary text, about
# 5,000 sentences, takes 0.7 s on one core, and the slowest input known, 1.1 s.
# A text that matches the data over and over is held by checks.MAX_MATCHES,
# and anything else by the time and memory limits below.
DEFAULT_MAX_BODY = 262_144
DEFAULT_SECONDS = 10.0
DEFAULT_MEMORY_MB = 1024
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# The Host and Origin headers a local service accepts: the MCP SDK's own list.
_LOCAL_HOST_HEADER = re.compile(r"(127\.0\.0\.1|localhost|\[::1\])(:\d+)?", re.IGNORECASE)
_LOCAL_ORIGIN = re.compile(r"http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?", re.IGNORECASE)

Body = Mapping[str, object]
T = TypeVar("T")


class Limits:
    """How long one request's checks may run and how much memory they may take.

    The checks run in worker processes (anyio.to_process), as many at once as
    `processes`. On Linux and macOS a timer in the worker stops checks past
    the time limit, and a capped address space stops them past the memory
    limit; a worker that still does not stop is killed. On Windows the
    worker is killed at the time limit, its start included. Either way the
    request gets TooMuchWork (413) and the service goes on. Waiting for a
    free worker does not count against the time limit.
    """

    def __init__(
        self, seconds: float = DEFAULT_SECONDS, memory_mb: int | None = DEFAULT_MEMORY_MB, processes: int | None = None
    ) -> None:
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("the time limit must be a number of seconds more than 0")
        if memory_mb is not None and memory_mb < 1:
            raise ValueError("the memory limit must be at least 1 MB")
        self.seconds = seconds
        self.memory_mb = memory_mb
        self.processes = processes or os.cpu_count() or 1
        self._free: anyio.CapacityLimiter | None = None

    async def run(self, call: Callable[[], T]) -> T:
        if self._free is None:
            self._free = anyio.CapacityLimiter(self.processes)
        memory = self.memory_mb * 1024 * 1024 if self.memory_mb else None
        async with self._free:
            try:
                # Where the worker times itself, this is only the backstop for
                # a worker that does not stop: its start does not count.
                with anyio.fail_after(self.seconds * 2 + 5 if TIMES_ITSELF else self.seconds):
                    return await anyio.to_process.run_sync(run_capped, call, memory, self.seconds, cancellable=True)
            except TimeoutError:
                raise TooMuchWork(
                    f"the checks took more than {self.seconds:g} s, this service's limit: check the text in parts"
                ) from None
            except MemoryError:
                raise TooMuchWork(
                    f"the checks needed more than {self.memory_mb} MB, this service's limit: check the text in parts"
                ) from None
            except anyio.BrokenWorkerProcess:
                raise TooMuchWork(
                    "the process checking it stopped, most likely out of memory: check the text in parts"
                ) from None


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


# Each route checks the request's shape here and gives back the work, which
# runs in a worker process under the service's limits.
Work = Callable[[], object]


def _prepare(body: Body) -> Work:
    _fields(body, ("brief", "data"), ("locale",))
    data = _data(body)
    return partial(run_prepare, _text(body, "brief"), data, _locale(body, data, ("es", "en"), "en"))


def _compose(body: Body) -> Work:
    _fields(body, ("draft", "data"), ("locale", "writer"))
    data = _data(body)
    locale = _locale(body, data, ("es", "en"), "en")
    return partial(run_compose, _text(body, "draft"), data, locale, writer=_text(body, "writer", "http client"))


def _verify(body: Body) -> Work:
    _fields(body, ("text", "data"), ("locale", "writer"))
    data = _data(body)
    locale = _locale(body, data, ("es", "en", "auto"), "auto")
    return partial(run_verify, _text(body, "text"), data, locale, writer=_text(body, "writer"))


def _receipt(body: Body) -> Work:
    _fields(body, ("receipt",), ("data",))
    return partial(run_check_receipt, _object(body, "receipt") or {}, _object(body, "data"))


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


def _check_headers(request: Request) -> None:
    """A JSON body, and on a local service, a local Host and Origin.

    A web page can make a browser send a plain-text POST anywhere, and point
    a name it controls at 127.0.0.1 (DNS rebinding). A JSON content type
    needs the browser to ask first, which this service never allows, and the
    Host header still carries the page's name.
    """
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("application/json"):
        raise _BadRequest("send the body as JSON, with Content-Type: application/json", 415)
    if not request.app.state.local:
        return
    if _LOCAL_HOST_HEADER.fullmatch(request.headers.get("host", "")) is None:
        raise _BadRequest("this service runs on this machine only: the Host header must be local", 421)
    origin = request.headers.get("origin")
    if origin is not None and _LOCAL_ORIGIN.fullmatch(origin) is None:
        raise _BadRequest("this service runs on this machine only: requests from web pages are refused", 403)


def _endpoint(handler: Callable[[Body], Work]) -> Callable[[Request], Awaitable[Response]]:
    async def endpoint(request: Request) -> Response:
        try:
            _check_headers(request)
            work = handler(await _payload(request))
            # In a worker process: off the event loop, so /health and other
            # requests still answer, and stopped if it runs past the limits.
            limits: Limits = request.app.state.limits
            result = await limits.run(work)
        except _BadRequest as exc:
            return JSONResponse({"error": exc.message}, status_code=exc.status)
        except TooMuchWork as exc:
            return JSONResponse({"error": str(exc)}, status_code=413)
        except ToolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except RecursionError:
            # Reading the JSON, or handing it to the worker: either way, the body.
            return JSONResponse({"error": "the body is nested too deeply"}, status_code=400)
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


def create_app(
    *, token: str | None, max_body: int = DEFAULT_MAX_BODY, host: str = "127.0.0.1", limits: Limits | None = None
) -> ASGIApp:
    """The service as an ASGI app: the REST routes and /mcp, behind the token if there is one.

    host is where it will listen. On this machine only (127.0.0.1), the MCP
    route also refuses requests whose Host header is not local, against DNS
    rebinding from a web page. limits bound each request's checks, on both
    doors; by default, DEFAULT_SECONDS and DEFAULT_MEMORY_MB.
    """
    if max_body < 1:
        raise ValueError("max_body must be at least 1 byte")
    limits = limits or Limits()
    # Stateless and plain JSON: any instance behind a load balancer can answer
    # any request, and no proxy has to keep a stream open.
    app = build_server(limits.run).streamable_http_app(
        stateless_http=True, json_response=True, max_request_body_size=max_body, host=host
    )
    app.state.max_body = max_body
    app.state.local = host in LOCAL_HOSTS
    app.state.limits = limits
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


def serve(
    *, host: str, port: int, token: str | None, max_body: int = DEFAULT_MAX_BODY, limits: Limits | None = None
) -> None:
    """Run the service until it is stopped."""
    app = create_app(token=token, max_body=max_body, host=host, limits=limits)
    uvicorn.run(app, host=host, port=port, server_header=False)
