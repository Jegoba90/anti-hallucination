"""What the writer works from: your numbers, your verdicts and your sources.

- A Fact is a number your code computed. The writer never types it: it writes
  a placeholder like {ventas}, and Python writes the figure.
- A Label is a verdict your code decided from the numbers («caída leve»,
  «riesgo alto»). The writer may place it, never choose it.
- A Source is a text the writer may summarize (a news note, a ticket, a page).
  A sentence that cites it may only state what it contains.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9_.\-]+")
_AUTO_DECIMALS_CAP = 6
_PERCENT_UNITS = frozenset({"%", "pct", "percent", "por ciento"})

Number = int | float | Decimal


def to_decimal(value: Number) -> Decimal:
    """The exact value as a Decimal: a float through its shortest repr, so -3.2 is -3.2."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"a fact value must be a number, not {type(value).__name__}")
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("a fact value must be finite")
        number = Decimal(repr(value))
    else:
        number = Decimal(value)
    if not number.is_finite():
        raise ValueError("a fact value must be finite")
    return number


def _check_name(kind: str, name: str) -> None:
    if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
        raise ValueError(f"{kind} name {name!r} must look like an identifier: letters, digits, underscore")


def _words(value: str | Sequence[str], what: str) -> tuple[str, ...]:
    items = (value,) if isinstance(value, str) else tuple(value)
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{what} must be non-empty text")
    return tuple(item.strip() for item in items)


@dataclass(frozen=True)
class Fact:
    """A number your code computed: the only place a figure can come from.

    name:     what the writer writes between braces: {ventas}
    value:    the number, in base units (4200000, not 4.2 with "millions")
    unit:     written after the figure; "%" makes it a percentage
    decimals: how many decimals Python writes; None takes them from the value
    label:    a plain name for it, for people reading the receipt
    subject:  the words that name what it measures ("ventas"), so a sentence
              about it can be checked even where it writes no figure
    change:   True when the sign is a direction (a variation, a delta): words
              like «cayeron» or «rose» must agree with it
    signed:   write a plus sign before positive values
    compact:  write 4200000 as «4,2 millones» / «4.2 million»
    """

    name: str
    value: Number
    unit: str = ""
    decimals: int | None = None
    label: str = ""
    subject: str | tuple[str, ...] = ()
    change: bool = False
    signed: bool = False
    compact: bool = False

    def __post_init__(self) -> None:
        _check_name("fact", self.name)
        to_decimal(self.value)
        if self.decimals is not None and (
            isinstance(self.decimals, bool) or not isinstance(self.decimals, int) or not 0 <= self.decimals <= 12
        ):
            raise ValueError("decimals must be an integer from 0 to 12")
        object.__setattr__(self, "subject", _words(self.subject, "a subject"))

    @property
    def number(self) -> Decimal:
        return to_decimal(self.value)

    @property
    def is_percent(self) -> bool:
        return self.unit.strip().casefold() in _PERCENT_UNITS

    @property
    def subjects(self) -> tuple[str, ...]:
        """The subject words, always as a tuple (__post_init__ normalizes them)."""
        return self.subject if isinstance(self.subject, tuple) else (self.subject,)

    def shown_decimals(self) -> int:
        if self.decimals is not None:
            return self.decimals
        exponent = self.number.as_tuple().exponent
        written = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        return min(written, _AUTO_DECIMALS_CAP)

    def render(self, locale: str, modifier: str = "") -> str:
        """The figure as Python writes it, unit included.

        modifier "abs" drops the sign (the sentence carries it in words, as in
        «cayeron 3,2 %»); "signed" writes a plus sign before a positive value.
        """
        value = abs(self.number) if modifier == "abs" else self.number
        plus = modifier == "signed" or (self.signed and modifier != "abs")
        if self.compact and abs(value) >= 10**6:
            figure = _compact(value, self.decimals, locale)
        else:
            figure = format_number(value, self.shown_decimals(), locale)
        if plus and value > 0:
            figure = "+" + figure
        unit = self.unit.strip()
        if not unit:
            return figure
        if self.is_percent and unit == "%":
            return f"{figure} %" if locale == "es" else f"{figure}%"
        return f"{figure} {unit}"


def format_number(value: Decimal, decimals: int, locale: str) -> str:
    """«1.250,5» in Spanish, «1,250.5» in English; ROUND_HALF_UP."""
    quantum = Decimal(1).scaleb(-decimals)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    text = f"{abs(rounded):,.{decimals}f}"
    if locale == "es":
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return ("-" if rounded < 0 else "") + text


def _compact(value: Decimal, decimals: int | None, locale: str) -> str:
    """4200000 as «4,2 millones» or «4.2 million»."""
    magnitude = abs(value)
    if magnitude >= 10**12:
        scale, es_one, es_many, en = 10**12, "billón", "billones", "trillion"
    elif magnitude >= 10**9:
        scale, es_one, es_many, en = 10**9, "mil millones", "mil millones", "billion"
    else:
        scale, es_one, es_many, en = 10**6, "millón", "millones", "million"
    places = 1 if decimals is None else decimals
    shown = (value / scale).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    # «4,0 millones» reads «4 millones»: a coarser precision the fact still rounds to.
    figure = format_number(shown, 0 if shown == shown.to_integral_value() else places, locale)
    if locale == "es":
        word = es_one if figure in ("1", "-1") else es_many
    else:
        word = en
    return f"{figure} {word}"


@dataclass(frozen=True)
class Label:
    """A verdict your code decided from the numbers. The writer places it as {name}.

    rule says how it was decided, for the receipt: «-5 ≤ variación < -1».
    """

    name: str
    text: str
    rule: str = ""

    def __post_init__(self) -> None:
        _check_name("label", self.name)
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError(f"label {self.name!r} needs a text")


def classify(name: str, value: Number, thresholds: Sequence[tuple[Number, str]], otherwise: str) -> Label:
    """A Label from your own thresholds, with the rule that chose it.

    thresholds are (upper bound, text) pairs in increasing order: the first
    bound the value is below gives the text, and `otherwise` covers the rest.

        classify("tendencia", -3.2, [(-5, "caída fuerte"), (-1, "caída leve"),
                 (1, "estabilidad"), (5, "subida leve")], otherwise="subida fuerte")
        → Label("tendencia", "caída leve", rule="-5 ≤ -3.2 < -1")
    """
    number = to_decimal(value)
    bounds = [to_decimal(bound) for bound, _ in thresholds]
    if any(later <= earlier for earlier, later in zip(bounds, bounds[1:])):
        raise ValueError("thresholds must be strictly increasing")
    lower: Decimal | None = None
    for bound, (_, text) in zip(bounds, thresholds):
        if number < bound:
            rule = f"{number} < {bound}" if lower is None else f"{lower} ≤ {number} < {bound}"
            return Label(name, text, rule)
        lower = bound
    rule = f"{number} ≥ {lower}" if lower is not None else f"{number}"
    return Label(name, otherwise, rule)


@dataclass(frozen=True)
class Source:
    """A text the writer may summarize. Citing it as [id] limits a sentence to it.

    fallback is published, as is, in place of a citing sentence that fails a
    check: typically the headline, attributed («CoinDesk titula: «…»»).
    """

    id: str
    text: str
    title: str = ""
    name: str = ""
    fallback: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or _SOURCE_ID_RE.fullmatch(self.id) is None:
            raise ValueError(f"source id {self.id!r} may hold only letters, digits, '_', '-' and '.'")
        if not isinstance(self.text, str):
            raise TypeError("a source text must be text")

    @property
    def evidence(self) -> str:
        """Everything the writer read about this source."""
        return "\n".join(part for part in (self.name, self.title, self.text) if part)
