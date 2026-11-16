"""The MCP server: what a client such as Claude Desktop sees and gets back.

Every test goes through the protocol with the SDK's own client: in process for
most, and once over stdio, the way Claude Desktop and Claude Code launch it.
Skipped where the MCP SDK is not installed: it is the [mcp] extra.
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("mcp")
from mcp import Client, StdioServerParameters  # noqa: E402

from antihallucination.mcp_server import server  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_SALES = _ROOT / "examples" / "sales"
TOOLS = ["check_receipt", "compose_report", "prepare_report", "verify_text"]


def _data() -> dict:
    data = json.loads((_SALES / "data.json").read_text(encoding="utf-8"))
    data.pop("locale")  # passed to each tool as its own argument
    return data


def _call(name: str, arguments: dict):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())


def test_the_client_sees_four_read_only_tools() -> None:
    async def run():
        async with Client(server) as client:
            return (await client.list_tools()).tools, client.instructions

    tools, instructions = asyncio.run(run())

    assert sorted(tool.name for tool in tools) == TOOLS
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False
    assert instructions is not None and "prepare_report" in instructions


def test_prepare_report_gives_placeholders_and_no_figure() -> None:
    result = _call("prepare_report", {"brief": "Resumen trimestral.", "data": _data(), "locale": "es"})
    prepared = result.structured_content

    assert not result.is_error
    assert "{ventas}" in prepared["placeholders"]
    assert "{tendencia_ventas}" in prepared["placeholders"]
    assert "Do not type any figure, even one you know." in prepared["instructions"]
    for figure in ("1.250", "1250", "3,2", "86,40", "48 clientes"):
        assert figure not in prepared["instructions"]


def test_compose_report_writes_every_figure() -> None:
    draft = (_SALES / "draft.txt").read_text(encoding="utf-8")
    result = _call("compose_report", {"draft": draft, "data": _data(), "locale": "es"})
    report = result.structured_content

    assert not result.is_error
    assert report["text"] == (
        "En el tercer trimestre de 2026, las ventas cayeron 3,2 % hasta 1.250 unidades, una caída leve. "
        "Se sumaron 48 clientes y el ticket medio fue de 86,40 USD."
    )
    assert [sentence["action"] for sentence in report["sentences"]] == ["kept", "kept", "dropped"]
    assert report["receipt_digest"].startswith("sha256:")


def test_verify_text_finds_the_invented_figures() -> None:
    text = (_SALES / "written_by_an_ai.txt").read_text(encoding="utf-8")
    report = _call("verify_text", {"text": text, "data": _data(), "locale": "es"}).structured_content

    spans = [finding["span"] for sentence in report["sentences"] for finding in sentence["findings"]]
    assert {"5 %", "1.300", "crecieron", "Instagram"} <= set(spans)
    assert report["text"].startswith("Las ventas fueron 1.250 unidades (-3,2 %).")


def test_bad_data_comes_back_as_an_error_the_model_can_read() -> None:
    result = _call("verify_text", {"text": "x", "data": {"facts": [{"name": "a b", "value": 1}]}})

    assert result.is_error
    assert "facts[0]" in result.content[0].text


_OCTOBER = {
    "facts": [
        {"name": "ventas_septiembre", "value": 1240, "unit": "unidades", "subject": "ventas"},
        {"name": "ventas_octubre", "value": 1440, "unit": "unidades", "subject": "ventas"},
        {"name": "variacion_ventas", "compute": "percent_change", "from": "ventas_septiembre", "to": "ventas_octubre"},
    ]
}


def test_the_assistant_is_told_to_let_the_server_compute_changes() -> None:
    async def run():
        async with Client(server) as client:
            return (await client.list_tools()).tools, client.instructions

    tools, instructions = asyncio.run(run())
    schema = json.dumps(next(tool for tool in tools if tool.name == "compose_report").input_schema)

    assert instructions is not None and "Never compute a figure yourself" in instructions
    for key in ('"compute"', '"from"', '"to"', '"percent_change"', '"difference"'):
        assert key in schema


def test_compose_report_computes_the_change_and_its_receipt_says_so() -> None:
    draft = "Las ventas subieron {variacion_ventas}, hasta {ventas_octubre}."
    result = _call("compose_report", {"draft": draft, "data": _OCTOBER, "locale": "es"})
    report = result.structured_content

    assert not result.is_error
    assert report["text"] == "Las ventas subieron 16,1 %, hasta 1.440 unidades."
    derived = {fact["name"]: fact["derived"] for fact in report["receipt"]["facts"]}
    assert derived["ventas_octubre"] is None
    assert derived["variacion_ventas"] == {
        "compute": "percent_change",
        "from": "ventas_septiembre",
        "to": "ventas_octubre",
    }
    checked = _call("check_receipt", {"receipt": report["receipt"]}).structured_content
    assert checked == {"digest": "verified", "replay": "reproduced", "reason": ""}


def test_a_computed_fact_sent_with_a_value_is_refused() -> None:
    data = json.loads(json.dumps(_OCTOBER))
    data["facts"][2]["value"] = 16.1

    result = _call("compose_report", {"draft": "Las ventas subieron {variacion_ventas}.", "data": data, "locale": "es"})

    assert result.is_error
    assert "takes no value" in result.content[0].text


def test_a_receipt_from_the_server_verifies_and_replays() -> None:
    draft = (_SALES / "draft.txt").read_text(encoding="utf-8")
    receipt = _call("compose_report", {"draft": draft, "data": _data(), "locale": "es"}).structured_content[
        "receipt"
    ]

    checked = _call("check_receipt", {"receipt": receipt, "data": _data()}).structured_content

    assert checked == {"digest": "verified", "replay": "reproduced", "reason": ""}


def test_a_changed_receipt_is_caught() -> None:
    draft = (_SALES / "draft.txt").read_text(encoding="utf-8")
    receipt = _call("compose_report", {"draft": draft, "data": _data(), "locale": "es"}).structured_content[
        "receipt"
    ]
    receipt["text"] = "Las ventas se duplicaron."

    checked = _call("check_receipt", {"receipt": receipt}).structured_content

    assert checked["digest"] == "mismatch"
    assert checked["replay"] == "skipped"


def test_the_stdio_entry_point_serves_the_tools() -> None:
    """The command Claude Desktop runs: a separate process speaking over stdio."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "antihallucination.mcp_server"], cwd=str(_ROOT)
    )

    async def run():
        async with Client(params) as client:
            return sorted(tool.name for tool in (await client.list_tools()).tools)

    assert asyncio.run(asyncio.wait_for(run(), timeout=60)) == TOOLS
