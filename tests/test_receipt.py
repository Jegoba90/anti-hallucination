"""The receipt says what went in, what each check decided and what went out.

Its digest covers all of that, so a changed receipt no longer matches it. The
digest is unkeyed, so a match proves consistency, not authorship. What makes a
receipt more than a checksum is that its decision can be run again: replay()
rebuilds the inputs and must arrive at the same digest.
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import (
    Fact,
    Label,
    ReceiptStatus,
    ReplayStatus,
    Source,
    compose,
    replay,
    verify,
    verify_receipt,
)
from antihallucination.receipt import canonical_number

FACTS = [
    Fact("ventas", 1250, unit="unidades", subject="ventas"),
    Fact("variacion_ventas", -3.2, unit="%", change=True, subject="ventas"),
]
LABELS = [Label("periodo", "tercer trimestre de 2026", rule="from the calendar")]
SOURCES = [Source("n1", "Acme invested $2.1 billion in new plants.", name="Reuters")]
DRAFT = "En el {periodo}, las ventas cayeron {variacion_ventas:abs}. Reuters informa que Acme invirtió 3 mil millones [n1]."


def _receipt() -> dict:
    result = compose(DRAFT, FACTS, LABELS, SOURCES, locale="es")
    return json.loads(result.receipt.to_json())


class TestTheDigest:
    def test_a_fresh_receipt_verifies_and_survives_json(self) -> None:
        result = compose(DRAFT, FACTS, LABELS, SOURCES, locale="es")

        assert verify_receipt(result.receipt).status is ReceiptStatus.VERIFIED
        assert verify_receipt(result.receipt.to_json()).status is ReceiptStatus.VERIFIED

    @pytest.mark.parametrize(
        "change",
        [
            lambda r: r.__setitem__("text", r["text"] + " Y todo subió."),
            lambda r: r["decisions"][1].__setitem__("action", "kept"),
            lambda r: r["facts"][0].__setitem__("value", "1300"),
            lambda r: r["policy"].__setitem__("names", False),
            lambda r: r.__setitem__("input", "Otra cosa."),
        ],
        ids=["text", "decision", "fact", "policy", "input"],
    )
    def test_any_change_breaks_it(self, change) -> None:
        receipt = _receipt()
        change(receipt)

        assert verify_receipt(receipt).status is ReceiptStatus.MISMATCH

    def test_the_time_of_issue_is_outside_the_digest(self) -> None:
        receipt = _receipt()
        receipt["created_at"] = "2099-01-01T00:00:00Z"

        assert verify_receipt(receipt).status is ReceiptStatus.VERIFIED

    def test_the_same_inputs_give_the_same_digest(self) -> None:
        first = compose(DRAFT, FACTS, LABELS, SOURCES, locale="es").receipt
        second = compose(DRAFT, FACTS, LABELS, SOURCES, locale="es").receipt

        assert first.digest == second.digest

    @pytest.mark.parametrize("bad", ["not json", "[]", json.dumps({"recipe": "other/9", "digest": "sha256:00"})])
    def test_what_is_not_a_receipt_is_unreadable(self, bad: str) -> None:
        assert verify_receipt(bad).status is ReceiptStatus.UNREADABLE

    def test_the_source_text_stays_out_of_the_receipt(self) -> None:
        receipt = _receipt()

        assert "Acme invested" not in json.dumps(receipt)
        assert receipt["sources"][0]["sha256"].startswith("sha256:")


class TestReplay:
    def test_a_compose_receipt_reproduces(self) -> None:
        assert replay(_receipt(), SOURCES).status is ReplayStatus.REPRODUCED

    def test_a_verify_receipt_reproduces(self) -> None:
        result = verify("Las ventas fueron 1.300 unidades.", FACTS, locale="es")

        assert replay(result.receipt).status is ReplayStatus.REPRODUCED

    def test_it_needs_the_sources_it_names(self) -> None:
        check = replay(_receipt())

        assert check.status is ReplayStatus.INCOMPLETE
        assert "n1" in check.reason

    def test_another_source_under_the_same_id_is_caught(self) -> None:
        other = [Source("n1", "Acme invested $3 billion in new plants.", name="Reuters")]

        assert replay(_receipt(), other).status is ReplayStatus.DIFFERENT

    def test_a_tampered_receipt_is_not_replayed(self) -> None:
        receipt = _receipt()
        receipt["text"] = "Todo bien."

        assert replay(receipt, SOURCES).status is ReplayStatus.UNREADABLE


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("-3.2"), "-3.2"),
        (Decimal("1E+3"), "1000"),
        (Decimal("-0.0"), "0.0"),
        (Decimal("0.00"), "0.00"),
        (Decimal("1250"), "1250"),
    ],
)
def test_numbers_are_written_one_way(value: Decimal, expected: str) -> None:
    assert canonical_number(value) == expected
