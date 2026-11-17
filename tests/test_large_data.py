"""Large text and large data together: each check looks only at the data it can match.

These used to multiply: every figure against every fact, every sentence
against every source, a long chain of computed facts read once per link. Each
case below took from 5 to 20 seconds; now each runs in well under one, and the
budget leaves room for a slow machine and still fails long before the old
cost. Where the text really does match the data over and over (a figure that
stands for thousands of facts), MAX_MATCHES stops it with a clear error, and
the receipt stays small.
"""

import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import (  # noqa: E402
    MAX_MATCHES,
    Fact,
    Label,
    ReplayStatus,
    Result,
    Source,
    TooManyMatches,
    replay,
    verify,
)
from antihallucination import checks  # noqa: E402
from antihallucination.data import parse_data  # noqa: E402

BUDGET = 3.0  # seconds; each case takes well under 0.6 on a laptop
HALF = 64 * 1024  # the text, and the data, of a 128 KB request


def _word(i: int) -> str:
    """A distinct lowercase word for each i: «baaaa», «baaab»..."""
    out = ""
    for _ in range(4):
        out += "abcdefghijklmnopqrstuvwxyz"[i % 26]
        i //= 26
    return "b" + out


def _small_sources() -> list[Source]:
    return [Source(f"s{i}", "plain") for i in range(HALF // 30)]


def _big_source() -> list[Source]:
    return [Source("s1", "plain words here " * (HALF // 17))]


CASES: dict[str, Callable[[], object]] = {
    # Every figure against every fact: now only against those it can round to.
    "figures against many facts": lambda: verify("7 " * (HALF // 2), [Fact(f"f{i}", 1000 + i) for i in range(HALF // 30)]),
    # Every figure, move word and name against every source.
    "figures against many sources": lambda: verify("1 " * (HALF // 2), [], sources=_small_sources()),
    # Twice the size: move words were the cheapest of these to check.
    "move words against many sources": lambda: verify(
        "grew " * (HALF * 2 // 5), [], sources=[Source(f"s{i}", "plain") for i in range(HALF * 2 // 30)]
    ),
    "names against many sources": lambda: verify(
        " ".join("x B" + _word(i) for i in range(HALF // 8)), [], sources=_small_sources()
    ),
    # Distinct names and identifiers, each searched in one long source.
    "names against a long source": lambda: verify(
        " ".join("x B" + _word(i) for i in range(HALF // 8)), [], sources=_big_source()
    ),
    "identifiers against a long source": lambda: verify(
        " ".join(_word(i) + "9" for i in range(HALF // 7)), [], sources=_big_source()
    ),
    # Every sentence against every fact's subject.
    "subjects against many sentences": lambda: verify(
        "Flat. " * (HALF // 6), [Fact(f"f{i}", 1000 + i, subject=_word(i)) for i in range(HALF // 40)]
    ),
    # Every failed sentence against every fallback.
    "fallbacks against many failed sentences": lambda: verify(
        "bzzzz 9. " * (HALF // 9),
        [Fact(f"f{i}", 1000 + i, subject=_word(i)) for i in range(HALF // 80)] + [Fact("z", 1, subject="bzzzz")],
        fallbacks={_word(i): f"{{f{i}}}." for i in range(HALF // 80)},
    ),
    # A chain of computed facts listed last first: each waited for the next.
    "a chain of computed facts": lambda: parse_data(
        {
            "facts": [
                {"name": f"c{i}", "compute": "difference", "from": "base", "to": f"c{i + 1}"}
                for i in range(HALF * 2 // 70)
            ]
            + [{"name": f"c{HALF * 2 // 70}", "value": 5}, {"name": "base", "value": 1}]
        }
    ),
}


def _timed(run: Callable[[], object]) -> float:
    started = time.perf_counter()
    run()
    return time.perf_counter() - started


@pytest.mark.parametrize("name", list(CASES))
def test_text_and_data_together_are_read_about_once(name: str) -> None:
    elapsed = _timed(CASES[name])
    assert elapsed < BUDGET, f"{name}: {elapsed:.1f} s"


class TestTheMatchLimit:
    def test_a_figure_that_stands_for_thousands_of_facts_is_refused(self) -> None:
        # 3,000 sentences, each «7.», and 1,000 facts that are all 7: three
        # million matches, and a receipt that would list them all.
        facts = [Fact(f"f{i}", 7) for i in range(1000)]

        started = time.perf_counter()
        with pytest.raises(TooManyMatches, match=f"more than {MAX_MATCHES:,} times"):
            verify("7. " * 3000, facts)

        assert time.perf_counter() - started < BUDGET

    def test_a_verdict_repeated_in_thousands_of_labels_is_refused(self) -> None:
        labels = [Label(f"l{i}", "steady") for i in range(1000)]

        with pytest.raises(TooManyMatches):
            verify("Steady. " * 3000, [], labels)

    def test_a_long_report_stays_far_below_it(self) -> None:
        # Ten facts sharing a value and a subject, a long text naming them.
        facts = [Fact(f"region_{i}", 48, unit="clientes", subject="clientes") for i in range(10)]
        result = verify("Se sumaron 48 clientes. " * 2000, facts, locale="es")

        assert result.ok
        assert result.decisions[0].facts == tuple(f"region_{i}" for i in range(10))

    def test_a_replay_past_the_limit_says_why(self, monkeypatch: pytest.MonkeyPatch) -> None:
        facts = [Fact(f"f{i}", 7) for i in range(10)]
        result = verify("7. " * 10, facts)
        monkeypatch.setattr(checks, "MAX_MATCHES", 50)

        check = replay(result.receipt)

        assert check.status is ReplayStatus.DIFFERENT
        assert "more than 50 times" in check.reason


def test_a_figure_for_several_negative_facts_gives_one_finding() -> None:
    # «3,2 %» stands for three falls of 3.2 %, and no word says it fell.
    facts = [Fact(name, -3.2, unit="%", change=True, subject=name) for name in ("ventas", "margen", "costes")]

    result: Result = verify("Las ventas fueron 3,2 %.", facts, locale="es")

    dropped = [finding for finding in result.findings if finding.check == "sign_dropped"]
    assert len(dropped) == 1
    assert dropped[0].span == "3,2 %"
    assert dropped[0].detail.startswith("ventas is -3,2 % (so are 2 other facts this figure stands for)")
