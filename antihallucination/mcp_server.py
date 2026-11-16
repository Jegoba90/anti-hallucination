"""The layer as an MCP server, for Claude Desktop, Claude Code or any MCP client.

    pip install "antihallucination[mcp]"
    antihallucination-mcp            # or: python -m antihallucination.mcp_server

The model in the client is the writer. It puts the user's figures in `facts`,
asks prepare_report for the placeholders and the rules, writes its draft with
placeholders and sends it to compose_report: Python writes every figure, and
only the sentences that pass go out. verify_text audits a text that already
has its figures. The server calls no model and no network: the data stays on
the machine that runs it.
"""

from collections.abc import Mapping
from typing import Literal

from mcp.server.mcpserver import MCPServer
# pydantic builds the tools' schemas from these, and before Python 3.12 it
# refuses typing.TypedDict: the CI caught it on 3.11.
from typing_extensions import NotRequired, TypedDict
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__
from .core import ReplayStatus, Result, compose, replay, verify
from .data import Data, DataError, parse_data
from .prompt import build_prompt
from .receipt import ReceiptStatus, verify_receipt


# "from" is a Python keyword, hence the functional form, here and in LabelInput.
FactInput = TypedDict(
    "FactInput",
    {
        "name": str,
        "value": NotRequired[int | float],
        "unit": NotRequired[str],
        "decimals": NotRequired[int],
        "label": NotRequired[str],
        "subject": NotRequired[str | list[str]],
        "change": NotRequired[bool],
        "signed": NotRequired[bool],
        "compact": NotRequired[bool],
        "compute": NotRequired[Literal["percent_change", "difference"]],
        "from": NotRequired[str],
        "to": NotRequired[str],
    },
)
FactInput.__doc__ = (
    "A figure the user's data holds, with `value` in base units: 4200000, not 4.2 \"millions\". "
    "Or a change the server computes: `compute`, `from` and `to` (two fact names), and no value."
)

LabelInput = TypedDict(
    "LabelInput",
    {
        "name": str,
        "text": NotRequired[str],
        "rule": NotRequired[str],
        "from": NotRequired[str],
        "thresholds": NotRequired[list[tuple[int | float, str]]],
        "otherwise": NotRequired[str],
    },
)


class SourceInput(TypedDict):
    """A text the writer may summarize; a sentence that cites it as [id] may only state what it says."""

    id: str
    text: str
    title: NotRequired[str]
    name: NotRequired[str]
    fallback: NotRequired[str]


class DataInput(TypedDict, total=False):
    facts: list[FactInput]
    labels: list[LabelInput]
    sources: list[SourceInput]
    fallbacks: dict[str, str]
    known_names: list[str]
    checks: dict[str, bool]


class FindingOutput(TypedDict):
    check: str
    span: str
    detail: str


class SentenceOutput(TypedDict):
    action: str  # kept | dropped | replaced
    written: str  # the sentence as the writer wrote it
    published: str  # what went out in its place; empty when dropped
    findings: list[FindingOutput]


class ReportOutput(TypedDict):
    ok: bool
    text: str
    sentences: list[SentenceOutput]
    receipt_digest: str
    receipt: dict[str, object]


class PreparedOutput(TypedDict):
    instructions: str
    placeholders: list[str]


class ReceiptCheckOutput(TypedDict):
    digest: str  # verified | mismatch | unreadable
    replay: str  # reproduced | different | incomplete | unreadable | skipped
    reason: str


INSTRUCTIONS = """\
Use these tools whenever you write a text that states figures from data the user gave you, \
or check a text that does.

To write: put each figure the user gave in `facts` (name, value in base units, unit, and the \
`subject` it measures), each verdict the user's rules decided in `labels`, and any document to \
summarize in `sources`. Call prepare_report for the placeholders and the rules, write your draft \
with placeholders instead of figures, then call compose_report and give the user its `text`. \
Tell the user which sentences were dropped or replaced and why: the `sentences` field says it.

Never compute a figure yourself. For a change between two of the user's figures (a rise, a \
fall, a gap), add a fact with `compute` ("percent_change" or "difference"), `from` and `to` (the \
names of the two facts) and no value: the server computes it, and the receipt records it as \
computed. Give a variation as `value` with `change: true` only when the user's data states that \
variation itself.

To check a text that already has its figures, call verify_text with the same data.

Never retype or round a figure yourself: a placeholder is the only way a figure goes into the text."""

_READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

server = MCPServer(
    name="anti-hallucination",
    title="Anti-Hallucination",
    version=__version__,
    instructions=INSTRUCTIONS,
)


def _data(raw: Mapping[str, object] | None) -> Data:
    try:
        return parse_data(dict(raw or {}))
    except DataError as exc:
        raise ToolError(str(exc)) from exc


def _report(result: Result) -> ReportOutput:
    return {
        "ok": result.ok,
        "text": result.text,
        "sentences": [
            {
                "action": decision.action,
                "written": decision.input,
                "published": decision.output,
                "findings": [
                    {"check": finding.check, "span": finding.span, "detail": finding.detail}
                    for finding in decision.findings
                ],
            }
            for decision in result.decisions
        ],
        "receipt_digest": result.receipt.digest,
        "receipt": result.receipt.to_dict(),
    }


# What each tool does, shared with the HTTP service (http_server.py): the data
# comes as any JSON object, and the receipt can name who wrote the text.


def run_prepare(brief: str, data: Mapping[str, object], locale: str) -> PreparedOutput:
    parsed = _data(data)
    try:
        _, prompt = build_prompt(
            brief,
            list(parsed.facts),
            list(parsed.labels),
            list(parsed.sources),
            parsed.policy,
            locale,
            values_hidden=False,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    placeholders = [f"{{{fact.name}}}" for fact in parsed.facts]
    placeholders += [f"{{{label.name}}}" for label in parsed.labels]
    return {"instructions": prompt, "placeholders": placeholders}


def run_compose(draft: str, data: Mapping[str, object], locale: str, *, writer: str) -> ReportOutput:
    parsed = _data(data)
    try:
        result = compose(
            draft,
            parsed.facts,
            parsed.labels,
            parsed.sources,
            fallbacks=parsed.fallbacks,
            policy=parsed.policy,
            locale=locale,
            writer=writer,
        )
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
    return _report(result)


def run_verify(text: str, data: Mapping[str, object], locale: str, *, writer: str = "") -> ReportOutput:
    parsed = _data(data)
    try:
        result = verify(
            text,
            parsed.facts,
            parsed.labels,
            parsed.sources,
            fallbacks=parsed.fallbacks,
            policy=parsed.policy,
            locale=locale,
            writer=writer,
        )
    except (ValueError, TypeError) as exc:
        raise ToolError(str(exc)) from exc
    return _report(result)


def run_check_receipt(receipt: Mapping[str, object], data: Mapping[str, object] | None) -> ReceiptCheckOutput:
    check = verify_receipt(receipt)
    if check.status is not ReceiptStatus.VERIFIED:
        return {"digest": check.status.value, "replay": "skipped", "reason": check.reason}
    again = replay(receipt, _data(data).sources if data else ())
    reason = again.reason if again.status is not ReplayStatus.REPRODUCED else ""
    return {"digest": check.status.value, "replay": again.status.value, "reason": reason}


@server.tool(annotations=_READ_ONLY)
def prepare_report(brief: str, data: DataInput, locale: Literal["es", "en"] = "en") -> PreparedOutput:
    """Call first when you must write a text from the user's figures.

    Returns the placeholder for each figure and verdict, the shape Python will
    write each one in («N units»), which way each change went, and the rules.
    Write the draft with those placeholders, never typing a figure, then send
    it to compose_report with the same data. A change between two facts goes
    in as a fact with compute, from and to: the server computes it, not you.
    """
    return run_prepare(brief, data, locale)


@server.tool(annotations=_READ_ONLY)
def compose_report(draft: str, data: DataInput, locale: Literal["es", "en"] = "en") -> ReportOutput:
    """Fill a draft written with placeholders and keep only the sentences that pass.

    Python writes every figure. A sentence that types a figure, contradicts a
    change, names someone no source names, forecasts, claims certainty, states
    a cause or carries no data is dropped, or replaced by the user's fallback.
    Give the user `text`, and say what `sentences` reports as dropped.
    """
    return run_compose(draft, data, locale, writer="mcp client")


@server.tool(annotations=_READ_ONLY)
def verify_text(
    text: str, data: DataInput, locale: Literal["es", "en", "auto"] = "auto"
) -> ReportOutput:
    """Check a text that already has its figures against the user's data.

    Each figure must match a fact at the precision written, or appear in a
    label or source; directions, names, forecasts, certainty, causes and
    sentences with no data are checked as in compose_report. locale decides
    how «1.250» reads: "es" (1250), "en" (1.25) or "auto" (either).
    """
    return run_verify(text, data, locale)


@server.tool(annotations=_READ_ONLY)
def check_receipt(receipt: dict[str, object], data: DataInput | None = None) -> ReceiptCheckOutput:
    """Check a receipt from compose_report or verify_text, and run its decision again.

    The digest shows the receipt is internally consistent, not who issued it.
    Sources are recorded by hash only: pass the same data to replay a decision
    that used sources.
    """
    return run_check_receipt(receipt, data)


def main() -> None:
    """Serve over stdio, the transport Claude Desktop and Claude Code launch."""
    server.run("stdio")


if __name__ == "__main__":
    main()
