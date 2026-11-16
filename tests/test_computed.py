"""A change between two facts, computed by the package instead of typed by anyone.

The Claude Code session of 2026-11-16 found the gap: to write that sales rose
16.1 %, the model computed the figure itself and passed it in as a fact, and
the receipt came out verified. percent_change() and difference() take that
arithmetic away from the writer and from the caller, the checks hold a
computed fact to the two facts it comes from, and the receipt says which
figures were given and which were computed.
"""

import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import (
    Derivation,
    Fact,
    ReceiptStatus,
    ReplayStatus,
    compose,
    difference,
    percent_change,
    replay,
    verify,
    verify_receipt,
    write,
)
from antihallucination.data import DataError, parse_data
from antihallucination.prompt import build_prompt
from antihallucination.checks import Policy
from antihallucination.receipt import digest

SEPTEMBER = Fact("ventas_septiembre", 1240, unit="unidades", subject="ventas")
OCTOBER = Fact("ventas_octubre", 1440, unit="unidades", subject="ventas")
RISE = percent_change("variacion_ventas", SEPTEMBER, OCTOBER)
FACTS = [SEPTEMBER, OCTOBER, RISE]
DRAFT = "En octubre las ventas subieron {variacion_ventas}, hasta {ventas_octubre}."

CHURN_SEPTEMBER = Fact("churn_septiembre", 2.5, unit="%", subject="churn")
CHURN_OCTOBER = Fact("churn_octubre", 2.3, unit="%", subject="churn")


class TestComputing:
    def test_a_percent_change_is_exact_and_written_with_one_decimal(self) -> None:
        # (1440 − 1240) / 1240 × 100 = 16.129032…
        assert RISE.number == Decimal(200 * 100) / Decimal(1240)
        assert RISE.change and RISE.unit == "%" and RISE.subjects == ("ventas",)
        assert RISE.derived == Derivation("percent_change", "ventas_septiembre", "ventas_octubre")
        assert RISE.render("es") == "16,1 %"
        assert RISE.render("en", "signed") == "+16.1%"

    def test_a_percent_change_from_a_negative_start_keeps_the_direction(self) -> None:
        before = Fact("resultado_q2", -100, unit="USD")
        after = Fact("resultado_q3", -50, unit="USD")

        assert percent_change("mejora", before, after).number == 50

    def test_a_difference_keeps_the_unit_and_between_percentages_is_in_points(self) -> None:
        assert difference("cambio_ventas", SEPTEMBER, OCTOBER).render("es") == "200 unidades"

        churn = difference("cambio_churn", CHURN_SEPTEMBER, CHURN_OCTOBER)

        assert churn.unit == "pp"
        assert churn.render("es") == "-0,2 pp"
        assert churn.subjects == ("churn",)

    @pytest.mark.parametrize(
        ("start", "end", "message"),
        [
            (CHURN_SEPTEMBER, CHURN_OCTOBER, "reads two ways"),
            (Fact("altas_septiembre", 0, unit="clientes"), Fact("altas_octubre", 5, unit="clientes"), "from zero"),
            (SEPTEMBER, Fact("ingresos_octubre", 9000, unit="USD"), "one unit"),
        ],
    )
    def test_a_percent_change_with_no_honest_value_is_refused(self, start: Fact, end: Fact, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            percent_change("variacion", start, end)

    def test_a_fact_that_claims_to_be_computed_must_hold_the_computed_value(self) -> None:
        typed = Fact("variacion_ventas", 16.1, unit="%", change=True, subject="ventas", derived=RISE.derived)

        with pytest.raises(ValueError, match="does not hold the percent change"):
            compose(DRAFT, [SEPTEMBER, OCTOBER, typed], locale="es")

    def test_the_value_does_not_depend_on_the_callers_decimal_context(self) -> None:
        # A replay recomputes it: a caller with a lower precision must get the same digits.
        start, end = Fact("a", 123456, unit="u"), Fact("b", 234567, unit="u")
        with localcontext() as context:
            context.prec = 4
            low = percent_change("v", start, end)

        assert low.number == percent_change("v", start, end).number

    def test_write_refuses_a_bad_computed_fact_before_asking_the_writer(self) -> None:
        asked: list[str] = []

        def writer(system: str, prompt: str) -> str:
            asked.append(prompt)
            return DRAFT

        typed = Fact("variacion_ventas", 16.1, unit="%", change=True, subject="ventas", derived=RISE.derived)

        with pytest.raises(ValueError, match="does not hold the percent change"):
            write("Resumen de octubre.", [SEPTEMBER, OCTOBER, typed], writer=writer, locale="es")
        assert asked == []

    def test_a_computed_fact_needs_both_facts_it_comes_from(self) -> None:
        with pytest.raises(ValueError, match="not among the facts"):
            verify("Las ventas subieron un 16,1 %.", [OCTOBER, RISE], locale="es")

    def test_the_writer_is_told_what_was_computed_but_not_its_value(self) -> None:
        _, prompt = build_prompt("Resumen de octubre.", FACTS, [], [], Policy(), "es")

        assert "Python computed it: the percent change from {ventas_septiembre} to {ventas_octubre}." in prompt
        for figure in ("16", "1.240", "1.440", "200"):
            assert figure not in prompt


class TestTheChecks:
    def test_compose_writes_the_computed_change(self) -> None:
        result = compose(DRAFT, FACTS, locale="es")

        assert result.ok
        assert result.text == "En octubre las ventas subieron 16,1 %, hasta 1.440 unidades."

    def test_a_word_against_the_computed_direction_is_caught(self) -> None:
        result = compose("Las ventas cayeron {variacion_ventas:abs}.", FACTS, locale="es")

        assert [finding.check for finding in result.findings] == ["direction_contradiction"]

    def test_verify_takes_the_computed_change_at_the_precision_written(self) -> None:
        assert verify("Las ventas subieron un 16,1 %.", FACTS, locale="es").ok
        assert verify("Las ventas subieron un 16 %.", FACTS, locale="es").ok

        wrong = verify("Las ventas subieron un 20 %.", FACTS, locale="es")

        assert [finding.check for finding in wrong.findings] == ["unbacked_number"]

    def test_points_are_not_read_as_percent(self) -> None:
        facts = [CHURN_SEPTEMBER, CHURN_OCTOBER, difference("cambio_churn", CHURN_SEPTEMBER, CHURN_OCTOBER)]

        assert verify("El churn bajó 0,2 pp.", facts, locale="es").ok
        assert not verify("El churn bajó 0,2 %.", facts, locale="es").ok


class TestTheReceipt:
    def test_it_says_which_figures_were_given_and_which_computed(self) -> None:
        receipt = compose(DRAFT, FACTS, locale="es").receipt.to_dict()

        assert {fact["name"]: fact["derived"] for fact in receipt["facts"]} == {  # type: ignore[attr-defined]
            "ventas_septiembre": None,
            "ventas_octubre": None,
            "variacion_ventas": {"compute": "percent_change", "from": "ventas_septiembre", "to": "ventas_octubre"},
        }

    def test_a_receipt_with_a_computed_change_replays(self) -> None:
        assert replay(compose(DRAFT, FACTS, locale="es").receipt).status is ReplayStatus.REPRODUCED

    def test_an_edited_computed_value_does_not_replay_even_with_a_fresh_digest(self) -> None:
        receipt = json.loads(compose(DRAFT, FACTS, locale="es").receipt.to_json())
        for fact in receipt["facts"]:
            if fact["name"] == "variacion_ventas":
                fact["value"] = "20"
        receipt["digest"] = digest(receipt)

        again = replay(receipt)

        assert verify_receipt(receipt).status is ReceiptStatus.VERIFIED
        assert again.status is ReplayStatus.DIFFERENT
        assert "does not hold the percent change" in again.reason


class TestTheDataFile:
    BASE = [
        {"name": "a", "value": 1, "unit": "u"},
        {"name": "b", "value": 2, "unit": "u"},
    ]

    def test_a_computed_fact_has_no_value_and_may_come_before_its_facts(self) -> None:
        data = parse_data(
            {
                "facts": [
                    {"name": "variacion_ventas", "compute": "percent_change", "from": "ventas_septiembre", "to": "ventas_octubre"},
                    {"name": "ventas_septiembre", "value": 1240, "unit": "unidades", "subject": "ventas"},
                    {"name": "ventas_octubre", "value": 1440, "unit": "unidades", "subject": "ventas"},
                ]
            }
        )

        assert [fact.name for fact in data.facts] == ["variacion_ventas", "ventas_septiembre", "ventas_octubre"]
        assert data.facts[0] == RISE

    def test_the_unit_it_would_take_anyway_may_be_repeated(self) -> None:
        # The Claude Code session of the fix sent one, as models do.
        computed = {"name": "v", "compute": "difference", "from": "a", "to": "b", "unit": "u"}

        assert parse_data({"facts": [*self.BASE, computed]}).facts[2].render("en") == "1 u"

    def test_decimals_given_override_the_default(self) -> None:
        computed = {"name": "v", "compute": "percent_change", "from": "a", "to": "b", "decimals": 0}

        assert parse_data({"facts": [*self.BASE, computed]}).facts[2].render("en") == "100%"

    @pytest.mark.parametrize(
        ("fact", "message"),
        [
            ({"name": "v", "compute": "percent_change", "from": "a", "to": "b", "value": 16.1}, "takes no value"),
            ({"name": "v", "compute": "difference", "from": "a", "to": "b", "unit": "%"}, "this change is in «u»"),
            ({"name": "v", "compute": "ratio", "from": "a", "to": "b"}, "compute must be"),
            ({"name": "v", "compute": "difference", "from": "a", "to": "nada"}, "names no fact: 'nada'"),
            ({"name": "v", "compute": "difference", "from": ["a"], "to": "b"}, "must be the name of a fact"),
            ({"name": "v", "from": "a", "to": "b", "value": 1}, "no compute"),
            ({"name": "v", "compute": "difference", "from": "a", "to": "b", "change": False}, "always a change"),
        ],
    )
    def test_a_computed_fact_that_cannot_be_computed_is_refused(self, fact: dict[str, object], message: str) -> None:
        with pytest.raises(DataError, match=message):
            parse_data({"facts": [*self.BASE, fact]})

    def test_a_fact_computed_from_itself_is_refused(self) -> None:
        itself = {"name": "x", "compute": "difference", "from": "a", "to": "x"}

        with pytest.raises(DataError, match=r"facts\[2\]\.to: a fact cannot be computed from itself"):
            parse_data({"facts": [*self.BASE, itself]})

    def test_facts_computed_from_each_other_are_refused(self) -> None:
        loop = [
            {"name": "x", "compute": "difference", "from": "a", "to": "y"},
            {"name": "y", "compute": "difference", "from": "a", "to": "x"},
        ]

        with pytest.raises(DataError, match="computed from facts that are computed from it"):
            parse_data({"facts": [*self.BASE, *loop]})
