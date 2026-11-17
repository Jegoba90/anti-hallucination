"""compose(): the writer writes the words, Python writes every figure.

The writer's draft carries placeholders, {ventas}; it may not type a figure.
A sentence that fails a check is dropped or replaced by one you wrote, never
repaired. These pin what goes out, what does not and why.
"""

import re
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import Fact, Label, Policy, Source, classify, compose
from antihallucination.receipt import canonical_number

FACTS = [
    Fact("ventas", 1250, unit="unidades", label="ventas del trimestre", subject="ventas"),
    Fact("variacion_ventas", -3.2, unit="%", change=True, subject="ventas"),
    Fact("clientes_nuevos", 48, unit="clientes", subject="clientes"),
    Fact("ticket_medio", 86.4, unit="USD", decimals=2, subject="ticket"),
]
LABELS = [
    Label("periodo", "tercer trimestre de 2026"),
    classify(
        "tendencia_ventas",
        -3.2,
        [(-5, "caída fuerte"), (-1, "caída leve"), (1, "estabilidad"), (5, "subida leve")],
        otherwise="subida fuerte",
    ),
]


def _es(draft: str, **kwargs: object):
    return compose(draft, FACTS, LABELS, locale="es", **kwargs)  # type: ignore[arg-type]


def _checks(result) -> list[str]:
    return [finding.check for finding in result.findings]


class TestPythonWritesTheFigures:
    def test_placeholders_are_filled_from_the_facts(self) -> None:
        result = _es("En el {periodo}, las ventas cayeron {variacion_ventas:abs} hasta {ventas}, una {tendencia_ventas}.")

        assert result.ok
        assert result.text == (
            "En el tercer trimestre de 2026, las ventas cayeron 3,2 % hasta 1.250 unidades, una caída leve."
        )

    def test_english_writes_english_figures(self) -> None:
        result = compose(
            "Revenue reached {revenue}, {change:signed} on the quarter.",
            [Fact("revenue", 4_200_000, unit="USD", compact=True), Fact("change", 3.2, unit="%", change=True)],
            locale="en",
        )

        assert result.text == "Revenue reached 4.2 million USD, +3.2% on the quarter."

    def test_no_figure_in_the_output_comes_from_the_writer(self) -> None:
        result = _es("Se sumaron {clientes_nuevos} y el ticket medio fue de {ticket_medio}.")
        rendered = [fact.render("es") for fact in FACTS]

        leftover = result.text
        for figure in rendered:
            leftover = leftover.replace(figure, "")
        assert result.ok
        assert not re.search(r"\d", leftover)

    @pytest.mark.parametrize("draft", ["Las ventas fueron 1.250 unidades.", "Se sumaron cuarenta y ocho clientes."])
    def test_a_typed_figure_is_dropped_even_when_it_is_right(self, draft: str) -> None:
        result = _es(draft)

        assert _checks(result) == ["typed_number"]
        assert result.text == ""

    @pytest.mark.parametrize(
        ("draft", "typed"),
        [("La meta subió ½ punto.", "½"), ("Es el Ⅲ trimestre.", "Ⅲ"), ("Va por el lote_3.", "lote_3")],
    )
    def test_no_numeral_slips_past_the_figure_reader(self, draft: str, typed: str) -> None:
        """The promise is that the writer typed no figure at all, in any script."""
        result = _es(draft, policy=Policy(directions=False, names=False))

        assert [(f.check, f.span) for f in result.findings] == [("typed_number", typed)]

    @pytest.mark.parametrize("draft", ["Las ventas fueron {ventass}.", "Fue una {tendencia_ventas:abs}."])
    def test_a_placeholder_it_cannot_fill_drops_the_sentence(self, draft: str) -> None:
        assert _checks(_es(draft)) == ["unknown_placeholder"]


class TestSignsAndDirections:
    def test_a_dropped_minus_needs_a_word_that_carries_it(self) -> None:
        assert _checks(_es("La variación fue de {variacion_ventas:abs}.")) == ["sign_dropped"]
        assert _es("Las ventas cayeron {variacion_ventas:abs}.").ok
        assert _es("Hubo una pérdida de {variacion_ventas:abs} en ventas.").ok

    def test_your_verdict_can_carry_the_minus(self) -> None:
        """Without this the writer had to say the fall twice: «una caída leve con una caída de 3,2 %»."""
        result = _es("Hubo una {tendencia_ventas} de {variacion_ventas:abs}.")

        assert result.ok
        assert result.text == "Hubo una caída leve de 3,2 %."

    def test_a_verdict_that_says_no_fall_does_not(self) -> None:
        steady = [Label("estado", "estabilidad")]

        result = compose("Hubo {estado} de {variacion_ventas:abs}.", FACTS, steady, locale="es")

        assert [finding.check for finding in result.findings] == ["sign_dropped"]

    def test_a_direction_against_the_sign_is_a_contradiction(self) -> None:
        checks = _checks(_es("Las ventas subieron {variacion_ventas:abs}."))

        assert "direction_contradiction" in checks

    def test_a_negated_direction_is_read_as_negated(self) -> None:
        assert _es("Las ventas no subieron: quedaron en {ventas}.").ok
        assert _checks(_es("Las ventas no cayeron.")) == ["direction_contradiction"]

    def test_a_move_nothing_backs_is_a_claim(self) -> None:
        result = _es("El ticket medio subió hasta {ticket_medio}.")

        assert _checks(result) == ["unbacked_direction"]

    def test_a_position_word_is_not_a_move(self) -> None:
        assert _es("Las ventas quedaron bajo el objetivo, en {ventas}.").ok


class TestClaimsTheNumbersDoNotMake:
    @pytest.mark.parametrize(
        ("draft", "check"),
        [
            ("Las ventas subirán el próximo trimestre.", "forecast"),
            ("Sin duda, fue un buen trimestre.", "certainty"),
            ("Las ventas cayeron {variacion_ventas:abs} debido a la estacionalidad.", "cause"),
        ],
    )
    def test_each_claim_drops_its_sentence(self, draft: str, check: str) -> None:
        assert check in _checks(_es(draft))

    def test_a_policy_can_turn_a_check_off(self) -> None:
        draft = "Las ventas cayeron {variacion_ventas:abs} debido a la estacionalidad."

        assert _es(draft, policy=Policy(causes=False)).ok

    def test_a_name_nobody_gave_is_dropped(self) -> None:
        result = _es("Se sumaron {clientes_nuevos} gracias a Instagram.", policy=Policy(causes=False))

        assert _checks(result) == ["unbacked_name"]
        assert _es(
            "Se sumaron {clientes_nuevos} desde Instagram.", policy=Policy(known_names=("Instagram",))
        ).ok


class TestFallbacks:
    FALLBACKS = {"ventas": "Las ventas fueron {ventas} ({variacion_ventas})."}

    def test_a_failed_sentence_is_replaced_by_yours(self) -> None:
        result = _es("Las ventas crecieron {variacion_ventas:abs}.", fallbacks=self.FALLBACKS)

        assert result.text == "Las ventas fueron 1.250 unidades (-3,2 %)."
        assert [decision.action for decision in result.decisions] == ["replaced"]

    def test_a_fallback_goes_out_once(self) -> None:
        result = _es(
            "Las ventas crecieron {variacion_ventas:abs}. Las ventas se dispararon.", fallbacks=self.FALLBACKS
        )

        assert result.text.count("Las ventas fueron") == 1
        assert [decision.action for decision in result.decisions] == ["replaced", "dropped"]

    def test_a_fallback_that_would_repeat_kept_figures_is_skipped(self) -> None:
        result = _es(
            "Las ventas cayeron {variacion_ventas:abs} hasta {ventas}. Las ventas se dispararon.",
            fallbacks=self.FALLBACKS,
        )

        assert result.text == "Las ventas cayeron 3,2 % hasta 1.250 unidades."

    @pytest.mark.parametrize(
        "fallbacks",
        [{"ventaz": "Las ventas fueron {ventas}."}, {"ventas": "Las ventas fueron {nada}."}],
    )
    def test_a_broken_fallback_is_your_error_and_raises(self, fallbacks: dict[str, str]) -> None:
        with pytest.raises(ValueError):
            _es("Las ventas fueron {ventas}.", fallbacks=fallbacks)


class TestSources:
    SOURCES = [
        Source(
            "n1",
            "Acme invested $2.1 billion in new plants, the company said.",
            name="Reuters",
            fallback="Reuters titula: «Acme invests $2.1 billion in new plants».",
        ),
        Source("n2", "Bitcoin fell 6% on Friday.", name="CoinDesk"),
    ]

    def _run(self, draft: str):
        return compose(draft, FACTS, LABELS, self.SOURCES, locale="es")

    def test_a_cited_sentence_may_copy_figures_from_its_source(self) -> None:
        assert self._run("Reuters informa que Acme invirtió 2,1 mil millones de dólares [n1].").ok

    def test_it_may_not_bring_a_figure_its_source_lacks(self) -> None:
        result = self._run("Reuters informa que Acme invirtió 3 mil millones de dólares [n1].")

        assert _checks(result) == ["unbacked_number"]
        assert result.text == "Reuters titula: «Acme invests $2.1 billion in new plants»."

    def test_another_sources_name_does_not_count(self) -> None:
        result = self._run("CoinDesk informa que Acme invirtió 2,1 mil millones de dólares [n1].")

        assert _checks(result) == ["unbacked_name"]

    def test_an_uncited_sentence_still_may_not_type_figures(self) -> None:
        assert _checks(self._run("Acme invirtió 2,1 mil millones de dólares.")) == ["typed_number"]


class TestLayoutAndErrors:
    def test_paragraphs_survive_and_dropped_ones_leave_no_gap(self) -> None:
        draft = "Sin duda fue récord.\n\nLas ventas fueron {ventas}.\n\nSe sumaron {clientes_nuevos}."

        assert _es(draft).text == "Las ventas fueron 1.250 unidades.\n\nSe sumaron 48 clientes."

    def test_two_facts_with_one_name_are_refused(self) -> None:
        with pytest.raises(ValueError):
            compose("{a}", [Fact("a", 1), Fact("a", 2)])

    def test_a_label_cannot_share_a_facts_name(self) -> None:
        with pytest.raises(ValueError):
            compose("{a}", [Fact("a", 1)], [Label("a", "uno")])

    def test_compose_writes_in_one_language(self) -> None:
        with pytest.raises(ValueError):
            compose("{a}", [Fact("a", 1)], locale="auto")

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "3"])
    def test_a_fact_must_be_a_finite_number(self, value: object) -> None:
        with pytest.raises((TypeError, ValueError)):
            Fact("a", value)  # type: ignore[arg-type]


class TestEverySentenceCarriesData:
    """A sentence with none of your data is the writer's opinion, whatever its words.

    Found on 2026-11-16 in the first run with a real model (gpt-oss-120b on
    Groq): two sentences were clean, and the third, «El desempeño general se
    mantiene dentro de los parámetros esperados.», passed every check. No word
    list knew «parámetros esperados»; the data has no expectation at all.
    """

    REAL_DRAFT = (
        "En el {periodo}, se vendieron {ventas} y se registraron {clientes_nuevos} con un ticket medio de "
        "{ticket_medio}. La {tendencia_ventas} se reflejó en una caída de {variacion_ventas:abs} respecto al "
        "trimestre anterior. El desempeño general se mantiene dentro de los parámetros esperados."
    )

    def test_the_real_models_opinion_is_cut(self) -> None:
        result = _es(self.REAL_DRAFT)

        assert [decision.action for decision in result.decisions] == ["kept", "kept", "dropped"]
        assert _checks(result) == ["unanchored"]
        assert "parámetros esperados" not in result.text

    def test_a_verdict_alone_carries_data(self) -> None:
        assert _es("Fue una {tendencia_ventas}.").ok

    def test_a_cited_sentence_carries_its_source(self) -> None:
        source = Source("n1", "Acme opened new plants.", name="Reuters")

        assert compose("Reuters informa que Acme abrió plantas [n1].", FACTS, LABELS, [source], locale="es").ok

    def test_a_sentence_that_already_failed_gets_no_second_reason(self) -> None:
        assert _checks(_es("Las ventas fueron 1.250 unidades.")) == ["typed_number"]

    def test_the_policy_can_turn_it_off(self) -> None:
        draft = "El desempeño general se mantiene dentro de los parámetros esperados."

        assert _es(draft, policy=Policy(anchored=False)).ok


def test_classify_records_the_rule_it_applied() -> None:
    label = LABELS[1]

    assert (label.text, label.rule) == ("caída leve", "-5 ≤ -3.2 < -1")
    with pytest.raises(ValueError):
        classify("x", 1, [(5, "a"), (1, "b")], otherwise="c")


class TestLongValues:
    """A value takes at most 40 digits written out in full, and each one is written.

    Found on 2026-11-17: a 64-byte request to the service with 1e-10000000
    got back a 10 MB receipt, and 1e40 with 12 decimals failed while rounding,
    as did any value past the 28 digits of Python's default decimal context.
    """

    @pytest.mark.parametrize(
        "value",
        [Decimal("1e40"), Decimal("1e-40"), Decimal("0e-40"), Decimal("1e-10000000"), Decimal("1e10000000"), 1e300],
    )
    def test_a_value_past_40_digits_is_refused(self, value: object) -> None:
        with pytest.raises(ValueError, match="at most 40 digits"):
            Fact("a", value)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("value", "written"),
        [
            (Decimal("1e39"), "1" + "0" * 39),
            (Decimal("1e-39"), "0." + "0" * 38 + "1"),
            (Decimal("0e10000000"), "0"),
        ],
    )
    def test_a_value_up_to_40_digits_goes_into_the_receipt_in_full(self, value: Decimal, written: str) -> None:
        assert canonical_number(Fact("a", value).number) == written

    def test_every_digit_is_written_whatever_the_callers_context(self) -> None:
        # 40 digits, written with 12 decimals: 52, past the default context's 28.
        fact = Fact("a", Decimal("-123456789012345678901234567890.1234567891"), decimals=12)
        expected = "123,456,789,012,345,678,901,234,567,890.123456789100"
        with localcontext() as context:
            context.prec = 4
            shown = (fact.render("en"), fact.render("en", "abs"))

        assert shown == ("-" + expected, expected)

    def test_a_compact_figure_does_not_depend_on_the_callers_context(self) -> None:
        fact = Fact("a", Decimal("1234567890123456789012345678901234567"), compact=True, decimals=3)
        with localcontext() as context:
            context.prec = 4
            shown = fact.render("en")

        assert shown == "1,234,567,890,123,456,789,012,345.679 trillion"
