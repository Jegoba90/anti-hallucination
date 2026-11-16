"""Every figure a text writes is found, and read the way its language reads it.

The number check is the guarantee that does not depend on a word list: a figure
either is one of your facts, rounded to the precision it was written with, or
it is in a source the sentence may use. That holds only if every figure is
found and read right, «1.250» and «1,250» included.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination.numbers import Mention, backed_by_values, evidence_values, extract, match_fact


def _one(text: str, locale: str = "auto") -> Mention:
    mentions = extract(text, locale)
    assert len(mentions) == 1, [mention.raw for mention in mentions]
    return mentions[0]


def _values(text: str, locale: str = "auto") -> list[Decimal]:
    return [reading.value for reading in _one(text, locale).readings]


class TestSeparators:
    @pytest.mark.parametrize(
        ("text", "locale", "expected"),
        [
            ("1.250", "es", [Decimal("1250")]),
            ("1.250", "en", [Decimal("1.250")]),
            ("1,250", "es", [Decimal("1.250")]),
            ("1,250", "en", [Decimal("1250")]),
            ("1.250", "auto", [Decimal("1250"), Decimal("1.250")]),
            ("1.250,5", "auto", [Decimal("1250.5")]),
            ("1,250.5", "auto", [Decimal("1250.5")]),
            ("3,2", "en", [Decimal("3.2")]),
            ("1.250.000", "es", [Decimal("1250000")]),
        ],
    )
    def test_each_language_reads_its_own_marks(self, text: str, locale: str, expected: list[Decimal]) -> None:
        assert _values(text, locale) == expected

    def test_the_precision_is_what_was_written(self) -> None:
        assert _one("3,2", "es").readings[0].step == Decimal("0.1")
        assert _one("86,40", "es").readings[0].step == Decimal("0.01")
        assert _one("1.250", "es").readings[0].step == Decimal("1")

    def test_a_malformed_group_has_no_reading(self) -> None:
        assert _one("1,2,3").readings == ()


class TestScales:
    def test_scale_words_and_suffixes(self) -> None:
        assert _values("1,2 millones", "es") == [Decimal("1200000")]
        assert _one("1,2 millones", "es").readings[0].step == Decimal("100000")
        assert _values("4bn") == [Decimal("4000000000")]
        assert _values("10k") == [Decimal("10000")]
        assert _values("2.1 billion", "en") == [Decimal("2100000000")]
        assert _values("2,1 mil millones", "es") == [Decimal("2100000000")]

    def test_the_spanish_billon_is_a_million_millions(self) -> None:
        assert _values("1 billón", "es") == [Decimal("1000000000000")]
        assert _values("1 billion", "en") == [Decimal("1000000000")]

    def test_the_false_friend_is_not_backed_by_its_source(self) -> None:
        """«6.3 billion» backs «6.300 millones» and «6.3», never «6,3 millones»."""
        values = evidence_values("Exchange hacked for $6.3 billion")

        assert backed_by_values(_one("6.300 millones", "es"), values)
        assert backed_by_values(_one("6,3", "es"), values)
        assert not backed_by_values(_one("6,3 millones", "es"), values)


class TestSignsPercentsAndIdentifiers:
    def test_a_sign_counts_only_where_it_can_be_one(self) -> None:
        mentions = extract("El 2026-11-14 cerró en -3,2 % y luego +5.", "es")

        assert [(m.raw, m.negative, m.signed) for m in mentions] == [
            ("2026", False, False),
            ("11", False, False),
            ("14", False, False),
            ("-3,2 %", True, True),
            ("+5", False, True),
        ]

    @pytest.mark.parametrize("text", ["3,2 %", "3.2%", "5 por ciento", "5 percent"])
    def test_percentages_are_marked(self, text: str) -> None:
        assert _one(text).percent

    @pytest.mark.parametrize("text", ["Q3", "COVID-19", "5G", "B2B", "3er"])
    def test_digits_glued_to_letters_are_identifiers(self, text: str) -> None:
        mention = _one(f"en {text} hubo")

        assert mention.identifier
        assert mention.raw == text


class TestNumberWords:
    @pytest.mark.parametrize(
        ("text", "locale", "value"),
        [
            ("tres", "es", 3),
            ("treinta y cinco", "es", 35),
            ("dos mil", "es", 2000),
            ("un millón", "es", 1000000),
            ("mil millones", "es", 1000000000),
            ("twenty-five", "en", 25),
            ("a million", "en", 1000000),
        ],
    )
    def test_written_numbers_are_figures_too(self, text: str, locale: str, value: int) -> None:
        assert _values(f"hubo {text} casos", locale) == [Decimal(value)]

    def test_once_is_only_eleven_in_spanish(self) -> None:
        assert extract("it happened once", "auto") == []
        assert _values("once casos", "es") == [Decimal(11)]


class TestMatchingAFact:
    def test_rounding_to_the_written_precision_matches(self) -> None:
        assert match_fact(_one("1.250", "es"), Decimal("1249.6"), percent=False) == "exact"
        assert match_fact(_one("2,9 %", "es"), Decimal("2.94"), percent=True) == "exact"
        assert match_fact(_one("1.250", "es"), Decimal("1251"), percent=False) is None

    def test_one_significant_digit_must_be_exact(self) -> None:
        """Rounded, «3 %» would pass for 2.9 %, or for any target near it."""
        assert match_fact(_one("3 %"), Decimal("2.9"), percent=True) is None
        assert match_fact(_one("3 %"), Decimal("3"), percent=True) == "exact"
        assert match_fact(_one("tres", "es"), Decimal("3.2"), percent=False) is None

    def test_signs(self) -> None:
        assert match_fact(_one("-3,2 %", "es"), Decimal("-3.2"), percent=True) == "exact"
        assert match_fact(_one("3,2 %", "es"), Decimal("-3.2"), percent=True) == "abs"
        assert match_fact(_one("+3,2 %", "es"), Decimal("-3.2"), percent=True) == "sign"

    def test_a_percentage_never_matches_a_plain_count(self) -> None:
        assert match_fact(_one("48 %"), Decimal("48"), percent=False) is None
        assert match_fact(_one("48"), Decimal("48"), percent=False) == "exact"

    def test_an_identifier_is_never_a_quantity(self) -> None:
        assert match_fact(_one("Q3"), Decimal("3"), percent=False) is None


def test_an_unknown_locale_is_refused() -> None:
    with pytest.raises(ValueError):
        extract("1.250", "fr")
