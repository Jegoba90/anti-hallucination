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


class TestFiguresAsModelsWriteThem:
    """Correct sentences the checks cut for how a figure was written.

    Found in the evaluation's pilot on 2026-11-18, in reports by gpt-oss-120b
    and qwen3.8-27b: 19 correct sentences cut, every one for one of these.
    """

    def test_thousands_grouped_with_a_narrow_space(self) -> None:
        facts = [Fact("usuarios", 83662, unit="usuarios", subject="usuarios")]

        assert verify("La base de usuarios activos llegó a 83 662.", facts, locale="es").ok

    def test_a_version_a_source_wrote(self) -> None:
        sources = [Source("s1", "Los pedidos no sincronizan desde la versión 3.2.4. Hay 11 reportes.", name="Ticket 8144")]
        text = "El ticket 8144 reporta 11 casos de pedidos que no sincronizan desde la versión 3.2.4."

        assert ("unbacked_number", "3.2.4") not in _found(verify(text, sources=sources, locale="es"))

    def test_a_version_nobody_wrote_is_still_found(self) -> None:
        sources = [Source("s1", "Los pedidos no sincronizan desde la versión 3.2.4.", name="Ticket 8144")]

        result = verify("Los pedidos no sincronizan desde la versión 3.2.5.", sources=sources, locale="es")

        assert ("unbacked_number", "3.2.5") in _found(result)

    def test_a_figure_in_what_a_fact_measures(self) -> None:
        facts = [Fact("volumen", 141_600_000_000, unit="USD", label="volumen operado en 24 horas", subject="volumen")]

        assert verify("El volumen operado en 24 horas fue de 141,6 mil millones de USD.", facts, locale="es").ok
        assert verify("The 24-hour trading volume was 141.6 billion USD.", facts, locale="en").ok is False  # «horas» ≠ «hour»
        # The name backs the figure with its word, not the same digits elsewhere.
        assert ("unbacked_number", "24") in _found(verify("El volumen fue de 24 mil millones de USD en 24 días.", facts, locale="es"))
        assert ("unbacked_number", "24 %") in _found(verify("El volumen subió 24 %.", facts, locale="es"))

    def test_a_computed_change_as_python_writes_it(self) -> None:
        from antihallucination import percent_change

        before = Fact("caja_anterior", 89_924_000, unit="USD", subject="caja")
        after = Fact("caja", 90_607_000, unit="USD", subject="caja")
        change = percent_change("variacion_caja", before, after, decimals=1)  # 0.7595… %, written «0,8 %»

        result = verify("La caja creció 0,8 %.", [before, after, change], locale="es")

        assert change.render("es") == "0,8 %"
        assert result.ok


class TestWordsAsModelsWriteThem:
    """More correct sentences cut in the evaluation's pilot (2026-11-18), for a word the lists lacked."""

    CONVERSION = [
        Fact("conversion_anterior", 5.5, unit="%", decimals=1, subject="conversión"),
        Fact("conversion", 4.0, unit="%", decimals=1, subject="conversión"),
    ]

    @pytest.mark.parametrize("verb", ["ha retrocedido", "ha caído", "ha bajado", "ha disminuido", "ha descendido"])
    def test_a_participle_carries_the_fall(self, verb: str) -> None:
        from antihallucination import difference

        facts = [*self.CONVERSION, difference("variacion_conversion", *self.CONVERSION, decimals=1)]

        assert verify(f"La conversión {verb} 1,5 puntos porcentuales, hasta el 4,0 %.", facts, locale="es").ok

    def test_a_gerund_with_se_carries_the_fall(self) -> None:
        from antihallucination import percent_change

        before, after = Fact("deuda_anterior", 3_374_000_000, unit="USD", subject="deuda"), Fact("deuda", 3_303_000_000, unit="USD", subject="deuda")
        facts = [before, after, percent_change("variacion_deuda", before, after, decimals=1)]

        assert verify("La deuda neta cerró en 3.303 millones de USD, reduciéndose un 2,1 %.", facts, locale="es").ok

    def test_a_participle_that_reads_as_an_adjective_is_not_a_move(self) -> None:
        facts = [Fact("clientes", 12, unit="clientes", subject="clientes")]

        result = verify("Un número reducido de clientes, 12, pidió la baja.", facts, locale="es")

        assert not {"unbacked_direction", "direction_contradiction", "sign_dropped"} & {f.check for f in result.findings}

    def test_a_known_name_in_the_possessive(self) -> None:
        facts = [Fact("tickets", 12476, unit="tickets", subject="tickets")]
        policy = Policy(known_names=("Marlow Supply",))

        assert verify("Marlow Supply's support team resolved 12,476 tickets.", facts, policy=policy, locale="en").ok
        assert verify("Marlow Supply’s support team resolved 12,476 tickets.", facts, policy=policy, locale="en").ok
        # A name nobody gave is still found in the possessive (the first word of a sentence is never checked).
        assert ("unbacked_name", "Goods") in _found(
            verify("Kestrel Goods' support team resolved 12,476 tickets.", facts, policy=policy, locale="en")
        )


class TestTheChangeAMoveTalksAbout:
    """Correct sentences cut for the change a move was judged against.

    Found in the evaluation's second round on the pilot (2026-11-24), in
    reports by gpt-oss-120b and qwen3.8-27b.
    """

    SAAS = [
        Fact("churn_change", 0.4, unit="pp", decimals=1, change=True, subject="churn"),
        Fact("nrr", 90, unit="%", subject=("NRR", "retention")),
        Fact("nrr_change", -4, unit="pp", change=True, subject=("NRR", "retention")),
    ]
    TICKETS = [
        Fact("recibidos", 4095, unit="tickets", subject=("tickets recibidos", "recibidos")),
        Fact("variacion_recibidos", -3.4, unit="%", decimals=1, change=True, subject=("tickets recibidos", "recibidos")),
        Fact("resueltos", 12316, unit="tickets", subject=("tickets resueltos", "resueltos")),
        Fact("variacion_resueltos", 9.3, unit="%", decimals=1, change=True, subject=("tickets resueltos", "resueltos")),
    ]
    FIRST = "Se recibieron 4.095 tickets, una disminución del 3,4 %. "

    def test_a_move_is_about_the_subject_it_names(self) -> None:
        # The nearer figure is NRR's, but the rise is churn's.
        text = "This rise in churn aligns with a 4 percentage point decline in NRR, which fell to 90%."

        assert verify(text, self.SAAS, locale="en").ok
        assert ("direction_contradiction", "fall") in _found(
            verify("This fall in churn aligns with a 4 percentage point decline in NRR.", self.SAAS, locale="en")
        )

    def test_only_the_words_right_after_the_move_name_its_subject(self) -> None:
        facts = [
            Fact("revenue_change", -5, unit="%", change=True, subject="revenue"),
            Fact("costs_change", 3, unit="%", change=True, subject="costs"),
        ]
        policy = Policy(known_names=("Europe",))

        # «costs» is three words past «fell»: the fall is not theirs.
        assert verify("Revenue fell in Europe as costs rose.", facts, policy=policy, locale="en").ok
        assert verify("The decline in revenue came as costs rose.", facts, locale="en").ok

    def test_points_stand_for_the_change_in_points(self) -> None:
        facts = [
            Fact("orders_change", 1.9, unit="%", decimals=1, change=True, subject="orders"),
            Fact("return_rate", 5.8, unit="%", decimals=1, subject=("returns", "return rate")),
            Fact("return_rate_change", -1.9, unit="pp", decimals=1, change=True, subject=("returns", "return rate")),
        ]
        text = "The return rate decreased to 5.8 %, 1.9 percentage points lower than the prior quarter."

        assert verify(text, facts, locale="en").ok  # «lower» was judged against the orders' +1.9 %
        # A change in % written in points is caught, where it used to pass as the orders' change.
        assert not verify("Online orders rose 1.9 percentage points.", facts, locale="en").ok

    def test_a_move_that_points_back_is_about_the_sentence_before(self) -> None:
        text = self.FIRST + "Pese a esta reducción en la afluencia, se resolvieron 12.316 tickets, un 9,3 % más."

        assert verify(text, self.TICKETS, locale="es").ok
        wrong = verify(self.FIRST + "Pese a este aumento en la afluencia, se resolvieron 12.316 tickets.", self.TICKETS, locale="es")
        assert ("direction_contradiction", "aumento") in _found(wrong)

    def test_a_pointer_with_a_time_word_points_at_the_time(self) -> None:
        facts = [Fact("variacion_ventas", -5, unit="%", change=True, subject="ventas")]

        result = verify("Las ventas cayeron 5 %. Este mes subieron.", facts, locale="es")

        # Judged as a move nothing backs, not against the sales of the sentence before.
        assert [finding.check for finding in result.decisions[1].findings] == ["unbacked_direction"]


class TestWhatASourceStates:
    """A cause or a date ahead that a source states may be repeated in its words (pilot, 2026-11-24)."""

    EMAILS = [
        Source(
            "s2",
            "Confirmation emails arrive up to 8 hours late because the email provider throttled sending. "
            "Traffic was moved to a backup provider.",
        )
    ]

    def test_a_cause_the_source_states(self) -> None:
        text = "Confirmation emails were delayed up to eight hours due to email‑provider throttling."

        assert verify(text, sources=self.EMAILS, locale="en").ok
        assert verify(text.replace(".", " [s2]."), sources=self.EMAILS, locale="en").ok

    def test_the_effect_has_to_be_the_sources_too(self) -> None:
        # The source's cause, joined to an effect it never gave it.
        result = verify("Customer satisfaction fell due to provider throttling.", sources=self.EMAILS, locale="en")

        assert ("cause", "due to") in _found(result)

    def test_a_cause_the_source_does_not_state(self) -> None:
        result = verify("Confirmation emails were delayed due to a database outage.", sources=self.EMAILS, locale="en")

        assert ("cause", "due to") in _found(result)

    def test_a_source_that_links_nothing_backs_no_cause(self) -> None:
        sources = [Source("s1", "Confirmation emails arrive 8 hours late. The email provider throttled sending.")]

        result = verify("Confirmation emails arrive 8 hours late due to provider throttling.", sources=sources, locale="en")

        assert ("cause", "due to") in _found(result)

    def test_only_the_cited_source_counts(self) -> None:
        sources = [*self.EMAILS, Source("s3", "Five customers in Tampa received invoices with the wrong tax.")]

        result = verify("Confirmation emails were delayed due to email provider throttling [s3].", sources=sources, locale="en")

        assert ("cause", "due to") in _found(result)

    def test_a_date_ahead_the_source_gives(self) -> None:
        sources = [Source("s1", "La red Telar activará la actualización «Faro» el 5 de mayo.")]

        text = "Asimismo, se informa que la red Telar activará la actualización «Faro» el 5 de mayo."
        assert verify(text, sources=sources, locale="es").ok
        changed = verify("La red Telar cancelará la actualización «Faro» el 5 de mayo.", sources=sources, locale="es")
        assert ("forecast", "cancelará") in _found(changed)
        assert ("forecast", "subirá") in _found(verify("El precio de ether subirá.", sources=sources, locale="es"))


class TestAReadingOfTheFigures:
    """«Lo que implica», «indicating», «sugiere»: a figure said again, or a reading of it (pilot, 2026-11-24)."""

    CONVERSION = [
        Fact("conversion", 4.0, unit="%", decimals=1, subject="conversión"),
        Fact("variacion_conversion", -1.5, unit="pp", decimals=1, change=True, subject="conversión"),
    ]

    @pytest.mark.parametrize("words", ["lo que implica", "lo que refleja", "reflejando"])
    def test_a_change_said_again_is_not_a_cause(self, words: str) -> None:
        text = f"La conversión se ubicó en 4,0 %, {words} una disminución de 1,5 pp respecto al mes anterior."

        assert verify(text, self.CONVERSION, locale="es").ok

    def test_more_read_into_the_change_is_a_cause(self) -> None:
        text = (
            "La conversión se ubicó en 4,0 %, lo que refleja una disminución de 1,5 pp que responde a la mayor "
            "competencia en el segmento de pymes."
        )

        assert ("cause", "lo que refleja") in _found(verify(text, self.CONVERSION, locale="es"))

    def test_a_negative_variation_is_a_fall(self) -> None:
        facts = [Fact("variacion_devoluciones", 0.9, unit="pp", decimals=1, change=True, subject="devoluciones")]
        text = "La tasa de devoluciones aumentó, lo que implica una variación negativa de 0,9 puntos porcentuales."

        assert ("direction_contradiction", "variación negativa") in _found(verify(text, facts, locale="es"))
        assert verify(text.replace("negativa", "positiva"), facts, locale="es").ok

    @pytest.mark.parametrize(
        "reading",
        [
            "indicating stronger demand",
            "suggesting a shift in demand",
            "signaling continued investment",
            "which contributed to the result",
        ],
    )
    def test_a_reading_of_the_figures_is_a_cause_in_any_grammar(self, reading: str) -> None:
        facts = [Fact("orders", 37225, unit="orders", subject="orders")]

        result = verify(f"Online orders reached 37,225, {reading}.", facts, locale="en")

        assert "cause" in {finding.check for finding in result.findings}

    @pytest.mark.parametrize("text", ["Estos indicadores sugieren una expansión.", "Los pedidos llegaron a 506, sugiriendo una mejora."])
    def test_a_reading_in_spanish(self, text: str) -> None:
        facts = [Fact("pedidos", 506, unit="pedidos", subject="pedidos")]

        assert "cause" in {finding.check for finding in verify(text, facts, locale="es").findings}

    def test_a_verdict_of_yours_after_a_reading_is_yours(self) -> None:
        facts = [Fact("nrr", 101, unit="%", subject="NRR"), Fact("variacion_nrr", 1, unit="pp", change=True, subject="NRR")]
        labels = [Label("tendencia", "subida leve")]

        assert verify("El NRR subió a 101 %, indicando una subida leve.", facts, labels, locale="es").ok
        result = verify("El NRR subió a 101 %, indicando una subida fuerte.", facts, labels, locale="es")
        assert ("cause", "indicando") in _found(result)
