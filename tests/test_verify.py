"""verify(): a finished text checked against your facts, labels and sources.

This is the audit mode: a model's answer, a report someone wrote, a summary
with figures typed in. Each figure must be one of your facts (rounded to the
precision written), a figure in a label, or a figure in a source the sentence
may use; each direction must agree with its change; each name must be in the
evidence.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import Fact, Label, Policy, Source, verify

FACTS = [
    Fact("ventas", 1250, unit="unidades", subject="ventas"),
    Fact("variacion_ventas", -3.2, unit="%", change=True, subject="ventas"),
    Fact("clientes_nuevos", 48, unit="clientes", subject="clientes"),
    Fact("ticket_medio", 86.4, unit="USD", decimals=2, subject="ticket"),
]
LABELS = [Label("periodo", "tercer trimestre de 2026")]
FALLBACKS = {
    "ventas": "Las ventas fueron {ventas} ({variacion_ventas}).",
    "clientes": "Se sumaron {clientes_nuevos} nuevos.",
}


def _es(text: str, **kwargs: object):
    return verify(text, FACTS, LABELS, locale="es", **kwargs)  # type: ignore[arg-type]


def _found(result) -> list[tuple[str, str]]:
    return [(finding.check, finding.span) for finding in result.findings]


class TestTheExampleFromTheProposal:
    """The case promised on 2026-11-15: the AI invents two figures and a direction."""

    TEXT = (
        "En el tercer trimestre de 2026, las ventas crecieron un 5 % hasta 1.300 unidades. "
        "Se sumaron 48 clientes nuevos gracias a la campaña de Instagram. "
        "El ticket medio fue de 86,40 USD."
    )

    def test_every_invented_claim_is_found(self) -> None:
        result = _es(self.TEXT, fallbacks=FALLBACKS)

        assert _found(result) == [
            ("unbacked_number", "5 %"),
            ("unbacked_number", "1.300"),
            ("direction_contradiction", "crecieron"),
            ("unbacked_name", "Instagram"),
            ("cause", "gracias a"),
        ]

    def test_pythons_sentences_go_out_in_their_place(self) -> None:
        result = _es(self.TEXT, fallbacks=FALLBACKS)

        assert result.text == (
            "Las ventas fueron 1.250 unidades (-3,2 %). Se sumaron 48 clientes nuevos. "
            "El ticket medio fue de 86,40 USD."
        )
        assert [decision.action for decision in result.decisions] == ["replaced", "replaced", "kept"]


class TestFigures:
    def test_a_clean_english_text_passes(self) -> None:
        result = verify(
            "Revenue rose 12% to $4.2 million in Q3.",
            [
                Fact("revenue", 4_200_000, unit="USD", subject="revenue"),
                Fact("revenue_change", 12, unit="%", change=True, subject="revenue"),
            ],
            [Label("quarter", "Q3 2026")],
        )

        assert result.ok

    def test_a_dropped_minus_without_a_word_is_found(self) -> None:
        assert _found(_es("La variación fue de 3,2 %.")) == [("sign_dropped", "3,2 %")]

    def test_the_opposite_sign_is_a_contradiction(self) -> None:
        assert _found(_es("Las ventas variaron +3,2 %.")) == [("direction_contradiction", "+3,2 %")]

    def test_a_percentage_cannot_borrow_a_count(self) -> None:
        assert _found(_es("La conversión fue del 48 %.")) == [("unbacked_number", "48 %")]

    def test_a_target_near_a_fact_is_not_taken_for_it(self) -> None:
        result = verify("Churn was 2.9%, below the 3% target.", [Fact("churn", 2.9, unit="%")], locale="en")

        assert _found(result) == [("unbacked_number", "3%")]

    @pytest.mark.parametrize(("locale", "ok"), [("es", True), ("auto", True), ("en", False)])
    def test_the_locale_decides_what_1250_means(self, locale: str, ok: bool) -> None:
        assert verify("Las ventas fueron 1.250 unidades.", FACTS, locale=locale).ok is ok

    def test_a_date_in_a_label_backs_its_figures(self) -> None:
        result = verify(
            "El 14 de noviembre de 2026 las ventas fueron 1.250 unidades.",
            FACTS,
            [Label("fecha", "14 de noviembre de 2026")],
            locale="es",
        )

        assert result.ok


class TestSources:
    SOURCES = [
        Source("n1", "Acme invested $2.1 billion in new plants, the company said.", name="Reuters"),
        Source("n2", "Bitcoin fell 6% to $62,000 on Friday.", name="CoinDesk"),
    ]

    def _run(self, text: str):
        return verify(text, sources=self.SOURCES, locale="es")

    def test_a_source_in_english_backs_a_sentence_in_spanish(self) -> None:
        assert self._run("Bitcoin cayó un 6 % hasta 62.000 dólares [n2].").ok

    def test_a_citation_limits_the_sentence_to_its_source(self) -> None:
        assert _found(self._run("Acme invirtió 62.000 dólares [n1].")) == [("unbacked_number", "62.000")]

    def test_an_uncited_sentence_may_use_any_source(self) -> None:
        assert self._run("Acme invirtió 2,1 mil millones de dólares, según Reuters.").ok

    def test_a_move_against_the_source_is_unbacked(self) -> None:
        assert _found(self._run("Bitcoin subió un 6 % [n2].")) == [("unbacked_direction", "subió")]


class TestNamesAndDirections:
    def test_known_names_and_generic_words_pass(self) -> None:
        text = "Durante noviembre, las ventas de la Región Norte fueron 1.250 unidades, en USD."

        assert _found(_es(text)) == [("unbacked_name", "Región"), ("unbacked_name", "Norte")]
        assert _es(text, policy=Policy(known_names=("Región Norte",))).ok

    def test_a_negated_fall_agrees_with_a_rise(self) -> None:
        result = verify(
            "Revenue didn't fall.", [Fact("change", 12, unit="%", change=True, subject="revenue")], locale="en"
        )

        assert result.ok

    def test_a_negated_fall_contradicts_a_fall(self) -> None:
        assert _found(_es("Las ventas no cayeron.")) == [("direction_contradiction", "cayeron")]

    def test_a_move_is_judged_against_the_subject_its_clause_names(self) -> None:
        """«subió» is the ticket's: it must not be read against the sales change."""
        facts = [*FACTS[:2], Fact("ticket_medio", 86.4, unit="USD", subject="ticket")]
        result = verify("Las ventas cayeron, y el ticket subió.", facts, locale="es")

        assert _found(result) == [("unbacked_direction", "subió")]

    def test_a_move_with_no_change_behind_it_is_unbacked(self) -> None:
        result = verify("Churn rose.", [Fact("churn", 2.9, unit="%", subject="churn")], locale="en")

        assert _found(result) == [("unbacked_direction", "rose")]


class TestEverySentenceCarriesData:
    def test_an_opinion_with_no_data_is_cut(self) -> None:
        result = _es("Las ventas fueron 1.250 unidades. El desempeño se mantiene dentro de lo esperado.")

        assert [decision.action for decision in result.decisions] == ["kept", "dropped"]
        assert [finding.check for finding in result.findings] == ["unanchored"]

    def test_a_move_checked_against_its_change_carries_data(self) -> None:
        assert _es("Las ventas cayeron.").ok

    def test_your_verdicts_words_carry_data(self) -> None:
        result = verify("Fue una caída leve.", FACTS, [Label("tendencia", "caída leve")], locale="es")

        assert result.ok

    def test_a_figure_a_source_backs_carries_data(self) -> None:
        source = Source("n1", "Acme invested $2.1 billion.", name="Reuters")

        assert verify("Acme invirtió 2,1 mil millones de dólares.", sources=[source], locale="es").ok


def test_the_sentence_opening_word_is_not_checked_as_a_name() -> None:
    """A known limit, pinned so it is not mistaken for a guarantee: without a
    dictionary «Acme» opening a sentence reads like «The». Put such names in
    known_names, or rely on their mentions mid-sentence."""
    result = verify("Acme sold 1,250 units.", [Fact("units", 1250)], locale="en")

    assert result.ok


class TestLongFacts:
    """A fact past 28 digits is compared digit by digit, not rounded first.

    Before 2026-11-17 its absolute value was rounded to the caller's decimal
    context, 28 digits by default, so a figure that differed after them passed.
    """

    DEBT = [Fact("deuda", Decimal("-1234567890123456789012345678901"), change=True, subject="deuda")]

    def test_the_exact_figure_passes(self) -> None:
        assert verify("La deuda cayó 1234567890123456789012345678901.", self.DEBT, locale="es").ok

    def test_a_figure_that_differs_past_28_digits_is_found(self) -> None:
        result = verify("La deuda cayó 1234567890123456789012345679000.", self.DEBT, locale="es")

        assert _found(result) == [("unbacked_number", "1234567890123456789012345679000")]
