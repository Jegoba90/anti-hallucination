"""write(): a model drafts, compose() decides what goes out.

These run with fake writers, so no key and no network: what is pinned is the
loop around the model. The first draft that passes goes out; a draft with
failed sentences gets one more try with the reasons; the attempt with the
fewest failures wins; a model that fails on a retry does not lose the draft
it already gave.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import Fact, Label, ReplayStatus, replay
from antihallucination.errors import WriterError
from antihallucination.writing import write, writer_name

FACTS = [
    Fact("ventas", 1250, unit="unidades", subject="ventas"),
    Fact("variacion_ventas", -3.2, unit="%", change=True, subject="ventas"),
]
LABELS = [Label("periodo", "tercer trimestre de 2026")]
GOOD = "En el {periodo}, las ventas cayeron {variacion_ventas:abs} hasta {ventas}."
BAD = "Las ventas crecieron {variacion_ventas:abs}. Fueron 1.300 unidades."


class Scripted:
    """A writer that returns its drafts in order and records what it was asked."""

    name = "test:scripted"

    def __init__(self, *drafts: str | Exception) -> None:
        self.drafts = list(drafts)
        self.prompts: list[str] = []

    def __call__(self, system: str, prompt: str) -> str:
        self.prompts.append(prompt)
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return draft


def _write(writer: Scripted, **kwargs: object):
    return write("Resumen de ventas.", FACTS, LABELS, writer=writer, locale="es", **kwargs)  # type: ignore[arg-type]


def test_a_draft_that_passes_goes_out_after_one_call() -> None:
    writer = Scripted(GOOD)
    written = _write(writer)

    assert written.text == "En el tercer trimestre de 2026, las ventas cayeron 3,2 % hasta 1.250 unidades."
    assert len(writer.prompts) == 1
    assert written.result.receipt.body["writer"] == "test:scripted"


def test_a_failed_draft_is_asked_again_with_the_reasons() -> None:
    writer = Scripted(BAD, GOOD)
    written = _write(writer)

    assert len(written.attempts) == 2
    assert written.result is written.attempts[1]
    assert written.result.ok
    retry = writer.prompts[1]
    assert retry.startswith(writer.prompts[0])
    assert "«crecieron» goes against the direction given for that value" in retry
    assert "-3,2" not in retry


def test_the_attempt_with_fewer_failures_goes_out() -> None:
    worse = BAD + " Sin duda fue un récord."
    written = _write(Scripted(BAD, worse))

    assert written.result is written.attempts[0]


def test_retries_zero_asks_once() -> None:
    writer = Scripted(BAD)
    written = _write(writer, retries=0)

    assert len(writer.prompts) == 1
    assert not written.result.ok


def test_a_writer_that_fails_first_raises() -> None:
    with pytest.raises(WriterError, match="no key"):
        _write(Scripted(WriterError("no key")))


def test_a_writer_that_fails_on_the_retry_keeps_the_first_draft() -> None:
    written = _write(Scripted(BAD, WriterError("rate limited")))

    assert len(written.attempts) == 1
    assert written.errors == ("rate limited",)


def test_a_writer_that_returns_no_text_is_an_error() -> None:
    def broken(system: str, prompt: str) -> str:
        return None  # type: ignore[return-value]

    with pytest.raises(WriterError):
        write("x", FACTS, writer=broken, locale="es")


def test_names_in_the_brief_count_as_given_and_its_figures_do_not() -> None:
    writer = Scripted("Para Acme: las ventas fueron {ventas}. Fueron 2026 en total.")
    written = write("Informe para Acme, año 2026.", FACTS, LABELS, writer=writer, locale="es", retries=0)

    checks = [finding.check for finding in written.result.findings]
    assert "unbacked_name" not in checks
    assert checks == ["typed_number"]


def test_the_receipt_of_a_written_text_replays_without_the_model() -> None:
    written = _write(Scripted(GOOD))

    assert replay(written.result.receipt).status is ReplayStatus.REPRODUCED


def test_writer_names() -> None:
    def my_model(system: str, prompt: str) -> str:
        return ""

    class Served:
        name = "anthropic:claude-opus-5-5"
        served_by = "claude-opus-4-8"

        def __call__(self, system: str, prompt: str) -> str:
            return ""

    assert writer_name(my_model) == "my_model"
    assert writer_name(Served()) == "anthropic:claude-opus-5-5 (served by claude-opus-4-8)"
