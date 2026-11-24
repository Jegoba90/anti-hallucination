"""Every figure a text writes, and what it can mean.

A report says «1.250», «1,250», «3,2 %», «1,2 millones», «4bn» or «tres», and
the same characters mean different values in Spanish and in English: «1.250»
is a thousand two hundred and fifty in one and one and a quarter in the other.
Each figure becomes the set of readings it can have, with the precision it was
written to, and a reading matches a fact when the fact rounds to it.

A token that glues digits to letters («Q3», «COVID-19», «5G»), or digits that
cannot be a number («3.2.4», a version), is not a quantity: it is checked as
written, like a name. Thousands may also be grouped with the typographic
spaces (narrow, no-break or thin: «83 662»), never with a plain space.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass
from functools import lru_cache
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, ROUND_HALF_UP, Context, Decimal, InvalidOperation

LOCALES = ("es", "en", "auto")
# Products and differences without rounding, whatever the caller's context:
# a figure is compared digit by digit. Never divide in it: 1/3 has no end.
_UNROUNDED = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)


@dataclass(frozen=True)
class Reading:
    """One value a figure can stand for."""

    value: Decimal  # magnitude in base units, any scale word applied
    step: Decimal  # the precision written, in base units: «3,2» is 0.1, «1,2 millones» 100000
    unscaled: Decimal  # the figure before its scale word: «1,2 millones» is 1.2
    # One significant digit («3 %», «tres», «5 millones») matches only exactly:
    # rounded, «3 %» would pass for any fact from 2.5 to 3.5, a target included.
    exact_only: bool = False


@dataclass(frozen=True)
class Mention:
    """A figure as the text wrote it."""

    raw: str
    start: int
    end: int
    readings: tuple[Reading, ...]
    negative: bool = False
    signed: bool = False  # the text wrote a sign: «-3,2», «+5»
    percent: bool = False
    points: bool = False  # «1,5 pp», «4 percentage points»: a change in points, never a fact in %
    identifier: bool = False  # «Q3», «COVID-19»: compared as written, never as a quantity


_SCALE_WORDS: tuple[tuple[str, int], ...] = (
    (r"mil\s+millones", 10**9),
    (r"billones", 10**12),
    (r"bill[oó]n", 10**12),
    (r"millones", 10**6),
    (r"mill[oó]n", 10**6),
    (r"mil", 10**3),
    (r"trillions?", 10**12),
    (r"billions?", 10**9),
    (r"millions?", 10**6),
    (r"thousands?", 10**3),
)
_SCALE_SUFFIXES: dict[str, int] = {
    "MM": 10**6, "mn": 10**6, "bn": 10**9, "tn": 10**12,
    "k": 10**3, "K": 10**3, "M": 10**6, "B": 10**9, "T": 10**12,
}  # fmt: skip
# Spanish «billón» is a million millions and English «billion» a thousand
# millions: the false friend reads as what each language says, as it should.

_SCALE_WORD_RE = "|".join(pattern for pattern, _ in _SCALE_WORDS)
# The spaces typography groups thousands with: narrow no-break, no-break, thin.
_GROUP_SPACES = "\u202f\u00a0\u2009"
_NUMBER_RE = re.compile(
    r"(?P<sign>[-+−])?"
    # A group of three, and no fourth digit: «3 2026» is two figures, both checked.
    r"(?P<digits>\d{1,3}(?:[" + _GROUP_SPACES + r"]\d{3})+(?!\d)(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"
    r"(?:(?P<suffix>MM|mn|bn|tn|[kKMBT])(?![^\W_])"
    r"|\s?(?P<scale>(?i:" + _SCALE_WORD_RE + r"))(?![^\W_]))?"
    r"(?:(?P<percent>\s?(?:%|(?i:por\s+ciento|percent|pct)\b))"
    # Points: «1,5 pp», «a 4-percentage-point fall», «0,9 puntos porcentuales»,
    # «16 puntos». Basis points («25 puntos básicos») are not points.
    r"|(?P<points>[\s‑-]?(?i:pp\b|p\.\s?p\.|percentage[\s‑-]+points?\b|puntos?\s+porcentuales?\b"
    r"|punto\s+porcentual\b|points?\b|puntos?\b(?!\s+b[aá]sicos?\b))))?"
)

_WORDS_ES: dict[str, int] = {
    "cero": 0, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciséis": 16, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiuno": 21, "veintiún": 21, "veintiun": 21, "veintidós": 22, "veintidos": 22,
    "veintitrés": 23, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiséis": 26,
    "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
    "cien": 100, "mil": 1000,
}  # fmt: skip
_WORDS_EN: dict[str, int] = {
    "zero": 0, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "thousand": 1000,
}  # fmt: skip
_TENS_ES = "treinta|cuarenta|cincuenta|sesenta|setenta|ochenta|noventa"
_UNITS_ES = "uno|una|un|dos|tres|cuatro|cinco|seis|siete|ocho|nueve"
_UNIT_VALUES_ES = {"uno": 1, "una": 1, "un": 1, **{w: _WORDS_ES[w] for w in _UNITS_ES.split("|")[3:]}}
_TENS_EN = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_UNITS_EN = "one|two|three|four|five|six|seven|eight|nine"
_UNIT_VALUES_EN = {"one": 1, **{w: _WORDS_EN[w] for w in _UNITS_EN.split("|")[1:]}}

_SCALE_AFTER_WORD = r"(?:\s+(?P<scale>" + _SCALE_WORD_RE + r"))?"


@lru_cache(maxsize=None)
def _word_patterns(locale: str) -> tuple[re.Pattern[str], ...]:
    words: dict[str, int] = {}
    if locale in ("es", "auto"):
        words.update(_WORDS_ES)
    if locale in ("en", "auto"):
        words.update(_WORDS_EN)
    if locale == "auto":
        words.pop("once", None)  # «once» is eleven in Spanish and one time in English
    single = "|".join(sorted(words, key=len, reverse=True))
    patterns = [
        re.compile(r"\b(?P<tens>" + _TENS_ES + r")\s+y\s+(?P<unit>" + _UNITS_ES + r")\b" + _SCALE_AFTER_WORD, re.I),
        re.compile(r"\b(?P<tens>" + _TENS_EN + r")[-\s](?P<unit>" + _UNITS_EN + r")\b" + _SCALE_AFTER_WORD, re.I),
        re.compile(r"\b(?P<one>un|una|one|a)\s+(?P<scale>" + _SCALE_WORD_RE + r")\b", re.I),
        re.compile(r"\b(?P<word>" + single + r")\b" + _SCALE_AFTER_WORD, re.I),
    ]
    if locale == "es":
        del patterns[1]
    elif locale == "en":
        del patterns[0]
    return tuple(patterns)


_IDENTIFIER_RE = re.compile(r"(?<![\w-])(?=[\w-]*\d)(?=[\w-]*[^\W\d_])[\w][\w-]*")


def _scale_of(word: str) -> int:
    for pattern, value in _SCALE_WORDS:
        if re.fullmatch(pattern, word, re.I | re.S):
            return value
    return 1


def _significant(digits: str) -> int:
    """Digits written, leading zeros aside: «0,05» has one, «1.250» four."""
    return len(re.sub(r"[.,\s]", "", digits).lstrip("0"))


def _digit_readings(digits: str, locale: str) -> list[tuple[Decimal, int]]:
    """(value, decimals written) for each way `digits` can be read."""
    if any(space in digits for space in _GROUP_SPACES):
        # Spaces group the thousands, so a mark after them is the decimal one.
        head, _, tail = re.sub(r"\s", "", digits).replace(",", ".").partition(".")
        return [(Decimal(f"{head}.{tail}" if tail else head), len(tail))]
    dots, commas = digits.count("."), digits.count(",")
    try:
        if not dots and not commas:
            return [(Decimal(digits), 0)]
        if dots and commas:
            # Both separators: the last one is the decimal mark.
            decimal_mark = "." if digits.rfind(".") > digits.rfind(",") else ","
            thousands = "," if decimal_mark == "." else "."
            head, _, tail = digits.replace(thousands, "").partition(decimal_mark)
            if "." in tail or "," in tail:
                return []
            return [(Decimal(f"{head}.{tail}"), len(tail))]
        separator = "." if dots else ","
        groups = digits.split(separator)
        if len(groups) > 2:
            # Several of one mark can only group thousands.
            if all(len(group) == 3 for group in groups[1:]):
                return [(Decimal("".join(groups)), 0)]
            return []
        head, tail = groups
        if len(tail) != 3:
            return [(Decimal(f"{head}.{tail}"), len(tail))]
        # «1.250» and «1,250»: thousands or decimals, depending on the language.
        thousands_reading = (Decimal(head + tail), 0)
        decimal_reading = (Decimal(f"{head}.{tail}"), 3)
        if locale == "auto":
            return [thousands_reading, decimal_reading]
        groups_thousands = (separator == ".") == (locale == "es")
        return [thousands_reading if groups_thousands else decimal_reading]
    except InvalidOperation:
        return []


def _glued_before(text: str, index: int) -> bool:
    """Whether the character before `index` joins the figure to a word."""
    if index == 0:
        return False
    before = text[index - 1]
    if before.isalnum() or before == "_":
        return True
    # «COVID-19», «SKU.123»: a joiner right after a letter.
    return before in "-./" and index >= 2 and text[index - 2].isalpha()


class _Taken:
    """The spans already read as a figure, in order and never overlapping.

    Each pattern below finds spans that do not overlap each other, so a span
    only has to be free of what the patterns before it took; kept in order,
    that takes a binary search instead of a pass over every span.
    """

    def __init__(self) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []

    def free(self, start: int, end: int) -> bool:
        index = bisect_right(self._ends, start)  # the first span that ends after `start`
        return index == len(self._ends) or self._starts[index] >= end

    def add(self, spans: list[tuple[int, int]]) -> None:
        merged = sorted([*zip(self._starts, self._ends), *spans])
        self._starts = [start for start, _ in merged]
        self._ends = [end for _, end in merged]


def extract(text: str, locale: str = "auto") -> list[Mention]:
    """Every figure in `text`, in order of appearance."""
    if locale not in LOCALES:
        raise ValueError(f"locale must be one of {LOCALES}, not {locale!r}")
    mentions: list[Mention] = []
    taken = _Taken()
    spans: list[tuple[int, int]] = []

    for match in _NUMBER_RE.finditer(text):
        digits_start = match.start("digits")
        sign = match.group("sign")
        start = match.start()
        # A sign is one only after a space, a bracket or the start: in
        # «2026-11-14» the dashes separate.
        if sign and start > 0 and not (text[start - 1].isspace() or text[start - 1] in "([«\"'“"):
            sign, start = None, digits_start
        if _glued_before(text, start):
            continue
        end = match.end()
        if end < len(text) and (text[end].isalnum() or text[end] == "_") and not match.group("percent"):
            continue  # «3er», «5G»: an identifier, handled below
        scale = 1
        if match.group("suffix"):
            scale = _SCALE_SUFFIXES[match.group("suffix")]
        elif match.group("scale"):
            scale = _scale_of(match.group("scale"))
        exact_only = _significant(match.group("digits")) < 2
        readings = tuple(
            Reading(
                value=_UNROUNDED.multiply(value, scale),
                step=Decimal(1).scaleb(-decimals) * scale,
                unscaled=value,
                exact_only=exact_only,
            )
            for value, decimals in _digit_readings(match.group("digits"), locale)
        )
        if not readings:  # «3.2.4»: no number reads that way, so it is written like a name
            mentions.append(
                Mention(raw=match.group("digits"), start=digits_start, end=match.end("digits"), readings=(), identifier=True)
            )
            spans.append((start, end))
            continue
        mentions.append(
            Mention(
                raw=text[start:end].strip(),
                start=start,
                end=end,
                readings=readings,
                negative=sign in ("-", "−"),
                signed=sign is not None,
                percent=bool(match.group("percent")),
                points=bool(match.group("points")),
            )
        )
        spans.append((start, end))
    taken.add(spans)

    spans = []
    for match in _IDENTIFIER_RE.finditer(text):
        if taken.free(match.start(), match.end()):
            mentions.append(
                Mention(raw=match.group(0), start=match.start(), end=match.end(), readings=(), identifier=True)
            )
            spans.append((match.start(), match.end()))
    taken.add(spans)

    for pattern in _word_patterns(locale):
        spans = []
        for match in pattern.finditer(text):
            if not taken.free(match.start(), match.end()):
                continue
            groups = match.groupdict()
            if groups.get("tens"):
                tens = groups["tens"].casefold()
                unit = groups["unit"].casefold()
                value = (_WORDS_ES.get(tens) or _WORDS_EN[tens]) + (
                    _UNIT_VALUES_ES.get(unit) or _UNIT_VALUES_EN[unit]
                )
            elif groups.get("one"):
                value = 1
            else:
                word = groups["word"].casefold()
                value = _WORDS_ES[word] if word in _WORDS_ES else _WORDS_EN[word]
            scale = _scale_of(groups["scale"]) if groups.get("scale") else 1
            base = Decimal(value)
            mentions.append(
                Mention(
                    raw=match.group(0),
                    start=match.start(),
                    end=match.end(),
                    readings=(Reading(value=_UNROUNDED.multiply(base, scale), step=Decimal(scale), unscaled=base, exact_only=True),),
                )
            )
            spans.append((match.start(), match.end()))
        taken.add(spans)

    return sorted(mentions, key=lambda mention: mention.start)


def evidence_values(text: str, locale: str = "auto") -> frozenset[Decimal]:
    """Every value a source's figures can stand for, scaled and as written.

    The writer may copy «6.3 billion» as «6.300 millones» or as «6.3»; it may
    not turn it into «6,3 millones». Read with "auto" by default: a source in
    English backs a sentence in Spanish, so «$62,000» backs «62.000».
    """
    values: set[Decimal] = set()
    for mention in extract(text, locale):
        for reading in mention.readings:
            values.add(reading.value)
            values.add(reading.unscaled)
    return frozenset(values)


def backed_by_values(mention: Mention, values: frozenset[Decimal]) -> bool:
    """Whether a figure is one of the values a source wrote (any sign)."""
    return any(reading.value in values for reading in mention.readings)


def match_fact(mention: Mention, value: Decimal, percent: bool, decimals: int | None = None) -> str | None:
    """How a figure matches a fact, rounding the fact to the written precision.

    "exact": same value and sign. "abs": the text dropped the sign of a negative
    fact, which a word like «cayeron» may carry. "sign": the text wrote the
    opposite sign. None: another number.

    decimals: how many decimals Python writes the fact with. A figure written
    to exactly that precision is the fact as Python writes it, even with one
    significant digit: 0.76 % written with one decimal is «0,8 %».

    The unit has to agree both ways: a figure in % is no fact in other units,
    and a figure in points («1,9 pp») is no fact in %, whose change in points
    it would be confused with.
    """
    if mention.identifier or (mention.percent and not percent) or (mention.points and percent):
        return None
    found: str | None = None
    for reading in mention.readings:
        tolerance = Decimal(0) if reading.exact_only else reading.step / 2
        target = value
        if (
            reading.exact_only
            and decimals is not None
            and reading.value == reading.unscaled
            and reading.step == Decimal(1).scaleb(-decimals)
        ):
            target = value.quantize(reading.step, rounding=ROUND_HALF_UP, context=_UNROUNDED)
        written = reading.value.copy_negate() if mention.negative else reading.value
        # Unrounded: abs() and a subtraction in the caller's context would
        # round a long figure to its 28 digits, and a wrong one could pass.
        if _UNROUNDED.subtract(target, written).copy_abs() <= tolerance:
            return "exact"
        if _UNROUNDED.subtract(target.copy_abs(), reading.value).copy_abs() <= tolerance:
            found = found or ("sign" if mention.signed else "abs")
    return found
