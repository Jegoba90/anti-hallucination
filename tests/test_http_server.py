"""The HTTP service a company runs in its own network: a REST API and MCP over HTTP.

The REST routes are called through Starlette's test client; MCP over HTTP is
served for real on a free local port and reached with the SDK's own client,
token and all. Skipped where the [server] extra is not installed.
"""

import asyncio
import json
import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("mcp")
pytest.importorskip("uvicorn")
import httpx2  # noqa: E402
import uvicorn  # noqa: E402
from mcp import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from antihallucination import __version__  # noqa: E402
from antihallucination.cli import main  # noqa: E402
from antihallucination.http_server import create_app  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_SALES = _ROOT / "examples" / "sales"
TOKEN = "test-token-0123456789abcdef"
TOOLS = ["check_receipt", "compose_report", "prepare_report", "verify_text"]
COMPOSED = (
    "En el tercer trimestre de 2026, las ventas cayeron 3,2 % hasta 1.250 unidades, una caída leve. "
    "Se sumaron 48 clientes y el ticket medio fue de 86,40 USD."
)


def _data() -> dict:
    """The sales example's data file as it is, locale included: the service takes it as the default."""
    return json.loads((_SALES / "data.json").read_text(encoding="utf-8"))


def _draft() -> str:
    return (_SALES / "draft.txt").read_text(encoding="utf-8")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(token=TOKEN)) as test_client:
        test_client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield test_client


class TestTheToken:
    def test_health_answers_without_it(self) -> None:
        with TestClient(create_app(token=TOKEN)) as anonymous:
            response = anonymous.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": __version__}

    @pytest.mark.parametrize("header", [None, "Bearer wrong-token-0123456789", TOKEN])
    def test_every_other_route_needs_it(self, header: str | None) -> None:
        headers = {"Authorization": header} if header else {}
        with TestClient(create_app(token=TOKEN)) as anonymous:
            for path in ("/v1/verify", "/v1/compose", "/mcp"):
                response = anonymous.post(path, json={}, headers=headers)

                assert response.status_code == 401, path
                assert response.headers["www-authenticate"] == "Bearer"

    def test_without_a_token_the_routes_are_open(self) -> None:
        with TestClient(create_app(token=None)) as anonymous:
            response = anonymous.post("/v1/verify", json={"text": "x", "data": {}})

        assert response.status_code == 200


class TestTheRestApi:
    def test_compose_writes_every_figure_and_names_the_writer(self, client: TestClient) -> None:
        response = client.post("/v1/compose", json={"draft": _draft(), "data": _data(), "writer": "acme:report-bot"})
        report = response.json()

        assert response.status_code == 200
        assert report["text"] == COMPOSED
        assert [sentence["action"] for sentence in report["sentences"]] == ["kept", "kept", "dropped"]
        assert report["receipt"]["writer"] == "acme:report-bot"
        assert report["receipt"]["locale"] == "es"  # the data file's, as the request gave none

    def test_verify_finds_the_invented_figures(self, client: TestClient) -> None:
        text = (_SALES / "written_by_an_ai.txt").read_text(encoding="utf-8")
        report = client.post("/v1/verify", json={"text": text, "data": _data(), "locale": "es"}).json()

        spans = [finding["span"] for sentence in report["sentences"] for finding in sentence["findings"]]
        assert {"5 %", "1.300", "crecieron", "Instagram"} <= set(spans)
        assert report["ok"] is False

    def test_prepare_gives_placeholders_and_no_figure(self, client: TestClient) -> None:
        prepared = client.post("/v1/prepare", json={"brief": "Resumen trimestral.", "data": _data()}).json()

        assert "{ventas}" in prepared["placeholders"]
        for figure in ("1.250", "1250", "3,2", "86,40"):
            assert figure not in prepared["instructions"]

    def test_a_receipt_from_the_service_verifies_and_replays(self, client: TestClient) -> None:
        receipt = client.post("/v1/compose", json={"draft": _draft(), "data": _data()}).json()["receipt"]

        checked = client.post("/v1/receipt", json={"receipt": receipt, "data": _data()}).json()

        assert checked == {"digest": "verified", "replay": "reproduced", "reason": ""}

    def test_decimals_in_the_request_stay_exact(self, client: TestClient) -> None:
        data = {"facts": [{"name": "margen", "value": 0.1, "unit": "%", "decimals": 1}]}
        report = client.post("/v1/compose", json={"draft": "El margen fue {margen}.", "data": data, "locale": "es"}).json()

        assert report["text"] == "El margen fue 0,1 %."
        assert report["receipt"]["facts"][0]["value"] == "0.1"

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            ([1, 2], "must be a JSON object"),
            ({"data": {}}, "missing keys: draft"),
            ({"draft": "x", "data": {}, "local": "es"}, "unknown keys: local"),
            ({"draft": "x", "data": {}, "locale": "auto"}, "locale must be one of: es, en"),
            ({"draft": 3, "data": {}}, "draft must be text"),
            ({"draft": "x", "data": []}, "data must be a JSON object"),
            ({"draft": "x", "data": {"facts": [{"name": "a b", "value": 1}]}}, "facts[0]"),
        ],
    )
    def test_a_bad_request_says_what_is_wrong(self, client: TestClient, body: object, message: str) -> None:
        response = client.post("/v1/compose", json=body)

        assert response.status_code == 400
        assert message in response.json()["error"]

    def test_a_body_that_is_not_json_is_refused(self, client: TestClient) -> None:
        response = client.post("/v1/verify", content=b"{not json", headers={"Content-Type": "application/json"})

        assert response.status_code == 400
        assert "not valid JSON" in response.json()["error"]

    def test_a_body_over_the_limit_is_refused(self) -> None:
        with TestClient(create_app(token=TOKEN, max_body=1000)) as small:
            small.headers["Authorization"] = f"Bearer {TOKEN}"
            response = small.post("/v1/verify", json={"text": "x" * 2000, "data": {}})

        assert response.status_code == 413
        assert "1000 bytes" in response.json()["error"]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def live_service() -> Iterator[str]:
    """The service on a real local port, the way a client reaches it."""
    port = _free_port()
    service = uvicorn.Server(uvicorn.Config(create_app(token=TOKEN), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=service.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not service.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("the service did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    service.should_exit = True
    thread.join(15)


def test_mcp_over_http_serves_the_tools_with_the_token(live_service: str) -> None:
    data = _data()
    data.pop("locale")  # an MCP tool takes it as its own argument

    async def run():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
            async with Client(streamable_http_client(f"{live_service}/mcp", http_client=http)) as mcp_client:
                tools = sorted(tool.name for tool in (await mcp_client.list_tools()).tools)
                result = await mcp_client.call_tool(
                    "compose_report", {"draft": _draft(), "data": data, "locale": "es"}
                )
                return tools, result

    tools, result = asyncio.run(asyncio.wait_for(run(), timeout=60))

    assert tools == TOOLS
    assert not result.is_error
    assert result.structured_content["text"] == COMPOSED


def test_mcp_over_http_refuses_a_client_without_the_token(live_service: str) -> None:
    async def run():
        async with httpx2.AsyncClient() as http:
            return await http.post(f"{live_service}/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})

    response = asyncio.run(asyncio.wait_for(run(), timeout=30))

    assert response.status_code == 401


class TestTheServeCommand:
    def test_it_will_not_open_beyond_this_machine_without_a_token(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("ANTIHALLUCINATION_TOKEN", raising=False)

        assert main(["serve", "--host", "0.0.0.0"]) == 2
        assert "set ANTIHALLUCINATION_TOKEN" in capsys.readouterr().err

    def test_a_short_token_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ANTIHALLUCINATION_TOKEN", "short")

        assert main(["serve"]) == 2
        assert "at least 16 characters" in capsys.readouterr().err

    def test_a_max_body_that_is_not_a_number_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("ANTIHALLUCINATION_TOKEN", raising=False)
        monkeypatch.setenv("ANTIHALLUCINATION_MAX_BODY", "1MB")

        assert main(["serve"]) == 2
        assert "whole number of bytes" in capsys.readouterr().err
