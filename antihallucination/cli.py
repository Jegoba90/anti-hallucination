"""python -m antihallucination: the method from the command line.

    verify   TEXT  --data DATA   check a finished text against your data
    compose  DRAFT --data DATA   fill a draft with placeholders and check it
    write    --data DATA --brief "..." [--writer claude]   have a model draft it
    receipt  RECEIPT [--data DATA]   check a receipt and run its decision again

TEXT and DRAFT are file paths, or - to read standard input.

Exit codes: 0 every sentence passed, 1 some sentence failed (the text printed
holds the ones that passed and your fallbacks), 2 the input could not be read,
3 the writer failed.
"""

import argparse
import json
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
