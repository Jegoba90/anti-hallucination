"""python -m antihallucination: the method from the command line.

    verify   TEXT  --data DATA   check a finished text against your data
    compose  DRAFT --data DATA   fill a draft with placeholders and check it
    write    --data DATA --brief "..." [--writer claude]   have a model draft it
    receipt  RECEIPT [--data DATA]   check a receipt and run its decision again
    serve    [--host H] [--port P]   serve the checks over HTTP: a REST API and MCP

TEXT and DRAFT are file paths, or - to read standard input. serve reads its
token from ANTIHALLUCINATION_TOKEN and needs the [server] extra.

Exit codes: 0 every sentence passed, 1 some sentence failed (the text printed
holds the ones that passed and your fallbacks), 2 the input could not be read,
3 the writer failed.
"""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .core import Result, ReplayStatus, compose, replay, verify
from .data import Data, DataError, load_data
from .errors import WriterError
from .receipt import ReceiptStatus, verify_receipt
from .writing import Writer, Written, write

_MARK = {"kept": "✓ kept    ", "replaced": "↺ replaced", "dropped": "✗ dropped "}
WRITERS = ("claude", "openai", "groq", "ollama", "compatible")
TOKEN_VARIABLE = "ANTIHALLUCINATION_TOKEN"
MAX_BODY_VARIABLE = "ANTIHALLUCINATION_MAX_BODY"
MIN_TOKEN_LENGTH = 16


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m antihallucination",
        description="Numbers decide; the AI only writes. Check texts against your data.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser, *, locales: Sequence[str]) -> None:
        command.add_argument("--data", required=True, help="JSON file with facts, labels, sources and fallbacks")
        command.add_argument("--locale", choices=list(locales), help="overrides the data file's locale")
        command.add_argument("--json", action="store_true", help="print the full result as JSON")
        command.add_argument("--receipt", help="also save the receipt to this file")

    check = commands.add_parser("verify", help="check a finished text against your data")
    check.add_argument("text", help="the text's file, or - for standard input")
    common(check, locales=("es", "en", "auto"))

    fill = commands.add_parser("compose", help="fill a draft with placeholders and check it")
    fill.add_argument("draft", help="the draft's file, or - for standard input")
    common(fill, locales=("es", "en"))

    draft = commands.add_parser("write", help="have a model draft the text, then check it")
    draft.add_argument("--brief", required=True, help="what to write, for whom, how long")
    draft.add_argument("--writer", choices=WRITERS, default="claude", help="which model writes (default: claude)")
    draft.add_argument("--model", help="the model; required except for claude (default claude-opus-5-5)")
    draft.add_argument("--base-url", help="the server, for --writer compatible or a non-default host")
    draft.add_argument("--retries", type=int, default=1, help="asks again with the reasons (default 1)")
    common(draft, locales=("es", "en"))

    receipt = commands.add_parser("receipt", help="check a receipt and run its decision again")
    receipt.add_argument("file", help="the receipt's JSON file")
    receipt.add_argument("--data", help="the data file, to pass the sources it names")

    service = commands.add_parser(
        "serve",
        help="serve the checks over HTTP: a REST API and MCP",
        description=f"Serve the checks over HTTP. The token comes from {TOKEN_VARIABLE}: with it, "
        "every request but GET /health needs 'Authorization: Bearer <token>'.",
    )
    service.add_argument("--host", default="127.0.0.1", help="where to listen (default 127.0.0.1: this machine only)")
    service.add_argument("--port", type=int, default=8000, help="the port (default 8000)")
    service.add_argument(
        "--max-body", type=int, help=f"the largest request accepted, in bytes (default 262144, or {MAX_BODY_VARIABLE})"
    )
    service.add_argument(
        "--no-auth", action="store_true", help="serve without a token beyond this machine: anyone who reaches it can use it"
    )
    return parser


def make_writer(args: argparse.Namespace) -> Writer:
    """The writer the arguments ask for.

    Raises ValueError for a missing argument and WriterError when the writer
    cannot be built (no SDK, no key).
    """
    if args.writer == "claude":
        from .writers.claude import DEFAULT_MODEL, ClaudeWriter

        return ClaudeWriter(args.model or DEFAULT_MODEL)
    from .writers.openai_compatible import OpenAICompatibleWriter

    if not args.model:
        raise ValueError(f"--writer {args.writer} needs --model")
    options: dict[str, object] = {"base_url": args.base_url} if args.base_url else {}
    if args.writer == "openai":
        return OpenAICompatibleWriter.openai(args.model, **options)
    if args.writer == "groq":
        return OpenAICompatibleWriter.groq(args.model, **options)
    if args.writer == "ollama":
        return OpenAICompatibleWriter.ollama(args.model, **options)
    if not args.base_url:
        raise ValueError("--writer compatible needs --base-url")
    return OpenAICompatibleWriter(args.model, base_url=args.base_url, api_key_env=None, provider="compatible")


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _show(result: Result, *, as_json: bool, written: Written | None = None) -> None:
    if as_json:
        out: dict[str, object] = {
            "ok": result.ok,
            "text": result.text,
            "decisions": [decision.to_dict() for decision in result.decisions],
            "receipt": result.receipt.to_dict(),
        }
        if written is not None:
            out["attempts"] = len(written.attempts)
            out["writer_errors"] = list(written.errors)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    if written is not None and len(written.attempts) > 1:
        print(f"Attempts: {len(written.attempts)} (the one with fewest failed sentences goes out)\n")
    for decision in result.decisions:
        print(f"{_MARK[decision.action]}  {decision.input}")
        for finding in decision.findings:
            print(f"      · {finding.check}: {finding.detail}")
        if decision.action == "replaced":
            print(f"      → {decision.output}")
    print("\nText:\n")
    print(result.text if result.text else "(nothing passed)")
    print(f"\nReceipt: {result.receipt.digest}")


def _save(result: Result, path: str | None) -> None:
    if path:
        Path(path).write_text(result.receipt.to_json() + "\n", encoding="utf-8")


def _locale(args: argparse.Namespace, data: Data, default: str) -> str:
    chosen: str = args.locale or data.locale or default
    if chosen == "auto" and default != "auto":
        # Python has to write the figures one way; it does not pick a language for you.
        raise ValueError(f"{args.command} writes figures in one language: pass --locale es or --locale en")
    return chosen


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    args = _parser().parse_args(argv)

    if args.command == "receipt":
        return _receipt(args)
    if args.command == "serve":
        return _serve(args)
    try:
        data = load_data(args.data)
    except DataError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    written: Written | None = None
    try:
        if args.command == "verify":
            result = verify(
                _read(args.text), data.facts, data.labels, data.sources,
                fallbacks=data.fallbacks, policy=data.policy, locale=_locale(args, data, "auto"),
            )
        elif args.command == "compose":
            result = compose(
                _read(args.draft), data.facts, data.labels, data.sources,
                fallbacks=data.fallbacks, policy=data.policy, locale=_locale(args, data, "en"),
            )
        else:
            written = write(
                args.brief, data.facts, data.labels, data.sources, writer=make_writer(args),
                fallbacks=data.fallbacks, policy=data.policy, locale=_locale(args, data, "en"),
                retries=args.retries,
            )
            result = written.result
    except WriterError as exc:
        print(f"Error: the writer failed: {exc}", file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    _show(result, as_json=args.json, written=written)
    _save(result, args.receipt)
    return 0 if result.ok else 1


def _serve(args: argparse.Namespace) -> int:
    """Run the HTTP service; refuse to open it beyond this machine without a token."""
    try:
        from .http_server import DEFAULT_MAX_BODY, LOCAL_HOSTS, serve
    except ImportError:
        print('Error: the service needs the server extra: pip install "antihallucination[server]"', file=sys.stderr)
        return 2
    token = os.environ.get(TOKEN_VARIABLE, "").strip() or None
    if token is not None and len(token) < MIN_TOKEN_LENGTH:
        print(f"Error: {TOKEN_VARIABLE} must be at least {MIN_TOKEN_LENGTH} characters long", file=sys.stderr)
        return 2
    if token is None and args.host not in LOCAL_HOSTS and not args.no_auth:
        print(
            f"Error: set {TOKEN_VARIABLE} to serve on {args.host}: without it, anyone who reaches the port "
            "can use the service. Pass --no-auth to serve without a token anyway.",
            file=sys.stderr,
        )
        return 2
    max_body = args.max_body
    if max_body is None:
        configured = os.environ.get(MAX_BODY_VARIABLE, "").strip()
        if configured and not configured.isdigit():
            print(f"Error: {MAX_BODY_VARIABLE} must be a whole number of bytes", file=sys.stderr)
            return 2
        max_body = int(configured) if configured else DEFAULT_MAX_BODY
    if max_body < 1:
        print("Error: the largest request must be at least 1 byte", file=sys.stderr)
        return 2
    guard = "every request but /health needs the token" if token else "no token: open to whoever reaches it"
    print(f"anti-hallucination on http://{args.host}:{args.port}: REST at /v1, MCP at /mcp; {guard}", file=sys.stderr)
    serve(host=args.host, port=args.port, token=token, max_body=max_body)
    return 0


def _receipt(args: argparse.Namespace) -> int:
    try:
        text = Path(args.file).read_text(encoding="utf-8")
        sources = load_data(args.data).sources if args.data else ()
    except (OSError, DataError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    check = verify_receipt(text)
    print(f"Digest: {check.status.value}" + (f" ({check.reason})" if check.reason else ""))
    if check.status is not ReceiptStatus.VERIFIED:
        return 1 if check.status is ReceiptStatus.MISMATCH else 2
    again = replay(text, sources)
    print(f"Replay: {again.status.value}" + (f" ({again.reason})" if again.reason else ""))
    if again.status is ReplayStatus.REPRODUCED:
        return 0
    return 2 if again.status in (ReplayStatus.INCOMPLETE, ReplayStatus.UNREADABLE) else 1
