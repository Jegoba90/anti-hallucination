"""A long text costs about as much as reading it once.

Each case is a text that used to make the checks read a sentence again for
every word in it, so its cost grew with the square of its length (one with
the cube) and a few kilobytes held a core for minutes. Now each runs in
hundredths of a second; the budget leaves room for a slow machine and still
fails long before the old cost.

The decisions themselves did not change: test_verify and test_compose pin
them, and these only time them.
"""

import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import Fact, Label, Result, Source, compose, verify
from antihallucination.numbers import extract
from antihallucination.text import split_sentences

FACTS = [
    Fact("revenue", 100, label="Revenue", subject="revenue"),
    Fact("revenue_change", 5, unit="%", change=True, subject="revenue"),
    Fact("drop", -3.2, unit="%", change=True, subject="margin"),
]
SOURCES = [Source("s1", "Emails were late because the provider throttled sending.")]
BUDGET = 3.0  # seconds; each case takes well under 0.3 on a laptop


def _repeat(unit: str, size: int) -> str:
    return unit * (size // len(unit))


def _timed(run: Callable[[], object]) -> float:
    started = time.perf_counter()
    run()
    return time.perf_counter() - started


CASES: dict[str, Callable[[], object]] = {
    # A move word in every clause-less stretch, its subject right there.
    "moves with their subject": lambda: verify(_repeat("revenue grew ", 32_000), FACTS),
    # Move words with no subject: the clause, then the whole sentence, is searched.
    "moves with no subject": lambda: verify(_repeat("sales grew ", 32_000), FACTS),
    # A figure that matches a change next to every move word.
    "moves next to their figures": lambda: verify(_repeat("revenue grew 5 % ", 32_000), FACTS),
    # A dropped minus with a negated fall before each one: the old cost was cubic.
    "dropped minus signs with negated falls": lambda: compose(_repeat("no fell {drop:abs} ", 16_000), FACTS),
    # A verdict next to every dropped minus.
    "dropped minus signs next to verdicts": lambda: compose(
        _repeat("{drop:abs} {trend} ", 32_000), FACTS, [Label("trend", "steady")]
    ),
    # Dots after single letters do not end a sentence, so the line never splits.
    "dots that end no sentence": lambda: verify(_repeat("a. ", 64_000), FACTS),
    # Digits and number words side by side: each figure read was checked
    # against every figure read before it.
    "figures next to number words": lambda: extract(_repeat("1 tres ", 64_000)),
    # Each move followed by the subject it names.
    "moves naming their subject": lambda: verify(_repeat("the rise in revenue ", 32_000), FACTS),
    # Each clause a move that points back to the sentence before.
    "moves pointing back": lambda: verify("Revenue grew 5 %. " + _repeat("despite this rise, ", 32_000), FACTS),
    # Each clause a cause the source states, compared with the source's words.
    "causes a source states": lambda: verify(_repeat("emails were late due to provider throttling, ", 32_000), FACTS, sources=SOURCES),
    # One long clause of causes: each reads only so far ahead.
    "causes in one long clause": lambda: verify(_repeat("due to provider throttling ", 32_000), FACTS, sources=SOURCES),
    # A change said again after every «which means».
    "changes said again": lambda: verify(_repeat("margin, which means a 3.2 % drop, ", 32_000), FACTS),
}


@pytest.mark.parametrize("name", list(CASES))
def test_a_long_sentence_is_read_once(name: str) -> None:
    elapsed = _timed(CASES[name])
    assert elapsed < BUDGET, f"{name}: {elapsed:.1f} s for one long sentence"


def test_a_run_of_dots_with_no_space_after_is_read_once() -> None:
    # The sentence splitter tried every dot as the start of a boundary, and
    # each try ran to the end of the run and back: 40 000 dots took 30 s.
    line = "." * 50_000 + "x"
    elapsed = _timed(lambda: split_sentences(line))
    assert elapsed < BUDGET, f"{elapsed:.1f} s to split one line of dots"
    assert split_sentences(line) == [line]


def _checks(result: Result) -> list[str]:
    return [finding.check for finding in result.findings]


def test_the_negation_three_words_back_is_read_past_a_long_word() -> None:
    # A negator counts in the three words before a move. Reading back only
    # that far must still reach past a long word, and stop at the third.
    long_word = "x" * 5_000
    # «not» is the third word back: «did not grow» contradicts a rise.
    assert _checks(verify(f"Revenue did not {long_word} grow.", FACTS)) == ["direction_contradiction"]
    # A fourth word back is out of reach: «grow» agrees with the rise.
    assert _checks(verify(f"Revenue did not a {long_word} {long_word} grow.", FACTS)) == []
