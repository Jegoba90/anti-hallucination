"""How check time grows with the size of the input, shape by shape: run it after a change to the checks.

Each shape is a kind of input that once made the checks slow: a long sentence
with no punctuation, a figure next to every move word, every figure against
every fact, many sources, a long chain of computed facts. Each runs at sizes
s, 2s, 4s... and prints the time and how much it grew from the size before:
about ×2 is linear, ×4 quadratic, ×8 cubic. A shape the checks refuse
(TooManyMatches) says so. Shapes that mix text and data split each size
about half and half.

    python tools/timing.py                          # every shape, 8 KB to 256 KB
    python tools/timing.py moves-with-subject --max-kb 64
    python tools/timing.py --list

tests/test_long_texts.py and tests/test_large_data.py hold the worst of these
to a time budget; this shows the whole curve.
"""

import argparse
import importlib
import io
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]

Run = Callable[[], object]
Shape = tuple[str, Callable[[ModuleType, float], Run]]


def load_checkout() -> ModuleType:
    """This checkout's package, not a copy pip installed in site-packages."""
    sys.path.insert(0, str(ROOT))
    package = importlib.import_module("antihallucination")
    if not Path(str(package.__file__)).resolve().is_relative_to(ROOT):
        raise SystemExit(f"imported {package.__file__} instead of this checkout's antihallucination")
    importlib.import_module("antihallucination.data")
    importlib.import_module("antihallucination.text")
    return package


def _repeat(unit: str, kb: float) -> str:
    return unit * max(1, int(kb * 1024 / len(unit)))


def _half(kb: float) -> int:
    return int(kb * 1024 / 2)


def _word(i: int) -> str:
    """A distinct lowercase word for each i: «baaaa», «baaab»..."""
    out = ""
    for _ in range(4):
        out += "abcdefghijklmnopqrstuvwxyz"[i % 26]
        i //= 26
    return "b" + out


def _facts(ah: ModuleType) -> list[object]:
    return [
        ah.Fact("revenue", 100, label="Revenue", subject="revenue"),
        ah.Fact("revenue_change", 5, unit="%", change=True, subject="revenue"),
        ah.Fact("drop", -3.2, unit="%", change=True, subject="margin"),
    ]


def _small_sources(ah: ModuleType, kb: float) -> list[object]:
    return [ah.Source(f"s{i}", "plain") for i in range(_half(kb) // 30)]


def _big_source(ah: ModuleType, kb: float) -> list[object]:
    return [ah.Source("s1", "plain words here " * (_half(kb) // 17))]


SHAPES: dict[str, Shape] = {
    # A long sentence: the text alone.
    "moves-with-subject": ("move words, their subject in the clause", lambda ah, kb: lambda: ah.verify(_repeat("revenue grew ", kb), _facts(ah))),
    "moves-no-subject": ("move words with no subject anywhere", lambda ah, kb: lambda: ah.verify(_repeat("sales grew ", kb), _facts(ah))),
    "moves-next-to-figures": ("a change's figure next to every move word", lambda ah, kb: lambda: ah.verify(_repeat("revenue grew 5 % ", kb), _facts(ah))),
    "negated-falls": ("compose: a dropped minus after a negated fall", lambda ah, kb: lambda: ah.compose(_repeat("no fell {drop:abs} ", kb), _facts(ah))),
    "verdicts-by-figures": ("compose: a verdict next to every dropped minus", lambda ah, kb: lambda: ah.compose(_repeat("{drop:abs} {trend} ", kb), _facts(ah), [ah.Label("trend", "steady")])),
    "capitals": ("capitalized words that are not the first", lambda ah, kb: lambda: ah.verify(_repeat("x Foo ", kb), _facts(ah))),
    "dots-that-do-not-split": ("dots after single letters: one long sentence", lambda ah, kb: lambda: ah.verify(_repeat("a. ", kb), _facts(ah))),
    "sentences-on-one-line": ("many sentences on one line", lambda ah, kb: lambda: ah.verify(_repeat("Revenue grew 5 %. ", kb), _facts(ah))),
    "figures-and-number-words": ("digits and number words side by side", lambda ah, kb: lambda: ah.verify(_repeat("1 tres ", kb), _facts(ah))),
    "run-of-dots": ("a run of dots with no space after it", lambda ah, kb: lambda: ah.text.split_sentences("." * int(kb * 1024) + "x")),
    # Text and data, about half and half.
    "figures-x-facts": ("every figure against every fact", lambda ah, kb: lambda: ah.verify("7 " * (_half(kb) // 2), [ah.Fact(f"f{i}", 1000 + i) for i in range(_half(kb) // 30)])),
    "figures-x-sources": ("figures against many small sources", lambda ah, kb: lambda: ah.verify("1 " * (_half(kb) // 2), [], sources=_small_sources(ah, kb))),
    "moves-x-sources": ("move words against many small sources", lambda ah, kb: lambda: ah.verify("grew " * (_half(kb) // 5), [], sources=_small_sources(ah, kb))),
    "names-x-sources": ("distinct names against many small sources", lambda ah, kb: lambda: ah.verify(" ".join("x B" + _word(i) for i in range(_half(kb) // 8)), [], sources=_small_sources(ah, kb))),
    "names-x-long-source": ("distinct names against one long source", lambda ah, kb: lambda: ah.verify(" ".join("x B" + _word(i) for i in range(_half(kb) // 8)), [], sources=_big_source(ah, kb))),
    "identifiers-x-long-source": ("distinct identifiers against one long source", lambda ah, kb: lambda: ah.verify(" ".join(_word(i) + "9" for i in range(_half(kb) // 7)), [], sources=_big_source(ah, kb))),
    "subjects-x-sentences": ("many facts' subjects against many sentences", lambda ah, kb: lambda: ah.verify("Flat. " * (_half(kb) // 6), [ah.Fact(f"f{i}", 1000 + i, subject=_word(i)) for i in range(_half(kb) // 40)])),
    "verdicts-x-sentences": ("many verdicts against many sentences", lambda ah, kb: lambda: ah.verify("Flat. " * (_half(kb) // 6), [], [ah.Label(f"l{i}", "verdict " + _word(i)) for i in range(_half(kb) // 40)])),
    "fallbacks-x-failures": ("many fallbacks against many failed sentences", lambda ah, kb: lambda: ah.verify("bzzzz 9. " * (_half(kb) // 9), [ah.Fact(f"f{i}", 1000 + i, subject=_word(i)) for i in range(_half(kb) // 80)] + [ah.Fact("z", 1, subject="bzzzz")], fallbacks={_word(i): f"{{f{i}}}." for i in range(_half(kb) // 80)})),
    "computed-chain": ("a chain of computed facts, listed last first", lambda ah, kb: lambda: ah.data.parse_data({"facts": [{"name": f"c{i}", "compute": "difference", "from": "base", "to": f"c{i + 1}"} for i in range(_half(kb) * 2 // 70)] + [{"name": f"c{_half(kb) * 2 // 70}", "value": 5}, {"name": "base", "value": 1}]})),
    # The text matches the data over and over: refused past MAX_MATCHES.
    "same-value": ("hundreds of facts with the value every figure has", lambda ah, kb: lambda: ah.verify("7. " * (_half(kb) // 3), [ah.Fact(f"f{i}", 7) for i in range(_half(kb) // 30)])),
    "same-verdict": ("hundreds of verdicts with the same words, quoted", lambda ah, kb: lambda: ah.verify("steady. " * (_half(kb) // 8), [], [ah.Label(f"l{i}", "steady") for i in range(_half(kb) // 30)])),
    # Still slow in the library (the service's time limit stops it).
    "shared-subject": ("many facts sharing the subject every sentence names", lambda ah, kb: lambda: ah.verify("Revenue rose. " * (_half(kb) // 14), [ah.Fact(f"f{i}", 1000 + i, subject="revenue") for i in range(_half(kb) // 28)])),
}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("shapes", nargs="*", help="the shapes to time (default: all; see --list)")
    parser.add_argument("--list", action="store_true", help="list the shapes and stop")
    parser.add_argument("--start-kb", type=float, default=8.0)
    parser.add_argument("--max-kb", type=float, default=256.0)
    parser.add_argument("--max-seconds", type=float, default=6.0, help="stop growing a shape once a run takes this long")
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):  # a console that cannot show «×» shows \xd7
        sys.stdout.reconfigure(errors="backslashreplace")
    if args.list:
        for name, (what, _) in SHAPES.items():
            print(f"{name:28} {what}")
        return 0
    unknown = [name for name in args.shapes if name not in SHAPES]
    if unknown:
        print(f"error: no shape named {', '.join(unknown)} (see --list)", file=sys.stderr)
        return 2
    ah = load_checkout()
    print(f"antihallucination {ah.__version__} from {Path(str(ah.__file__)).parent}")
    for name in args.shapes or list(SHAPES):
        _, build = SHAPES[name]
        kb, previous, cells = args.start_kb, 0.0, []
        while kb <= args.max_kb:
            started = time.perf_counter()
            try:
                build(ah, kb)()
                refused = ""
            except ah.TooManyMatches:
                refused = " refused"
            elapsed = time.perf_counter() - started
            growth = f" ×{elapsed / previous:.1f}" if previous > 0.01 else ""
            cells.append(f"{kb:g} KB {elapsed:.2f} s{growth}{refused}")
            previous = elapsed
            if elapsed > args.max_seconds:
                break
            kb *= 2
        print(f"{name:28} " + " | ".join(cells), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
