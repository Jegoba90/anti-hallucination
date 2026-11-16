"""Your facts, labels, sources and rules in one JSON file, for the command line.

    {
      "locale": "es",
      "facts": [
        {"name": "ventas", "value": 1250, "unit": "unidades", "subject": "ventas"},
        {"name": "variacion_ventas", "value": -3.2, "unit": "%", "decimals": 1,
         "change": true, "subject": "ventas"}
      ],
      "labels": [
        {"name": "periodo", "text": "tercer trimestre de 2026"},
        {"name": "tendencia", "from": "variacion_ventas",
         "thresholds": [[-5, "caída fuerte"], [-1, "caída leve"], [1, "estabilidad"]],
         "otherwise": "subida"}
      ],
      "sources": [{"id": "s1", "name": "Reuters", "title": "...", "text": "...", "fallback": "..."}],
      "fallbacks": {"ventas": "Las ventas fueron {ventas} ({variacion_ventas})."},
      "known_names": ["Acme"],
      "checks": {"causes": true}
    }

Numbers are read as exact decimals: -3.2 stays -3.2. A label with "from" is
decided by its thresholds from that fact's value, the same as classify().
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .checks import Policy
from .facts import Fact, Label, Number, Source, classify

_CHECKS = ("numbers", "names", "directions", "forecasts", "certainty", "causes", "anchored")


class DataError(ValueError):
    """The data file is not one this package can read; the message says where."""


@dataclass(frozen=True)
class Data:
    facts: tuple[Fact, ...] = ()
    labels: tuple[Label, ...] = ()
    sources: tuple[Source, ...] = ()
    fallbacks: dict[str, str] = field(default_factory=dict)
    policy: Policy = field(default_factory=Policy)
    locale: str | None = None


def load_data(path: str | Path) -> Data:
    """Read a data file. Raises DataError with the place that is wrong."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise DataError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        raw: object = json.loads(text, parse_float=Decimal)
    except ValueError as exc:
        raise DataError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise DataError(f"{path} must hold a JSON object")
    return parse_data({str(key): value for key, value in raw.items()})


def parse_data(raw: Mapping[str, object]) -> Data:
    """Build Data from an already parsed object."""
    unknown = set(raw) - {"locale", "facts", "labels", "sources", "fallbacks", "known_names", "checks"}
    if unknown:
        raise DataError(f"unknown keys: {', '.join(sorted(unknown))}")
    try:
        facts = tuple(_fact(item, f"facts[{index}]") for index, item in enumerate(_list(raw, "facts")))
        by_name = {fact.name: fact for fact in facts}
        labels = tuple(_label(item, f"labels[{index}]", by_name) for index, item in enumerate(_list(raw, "labels")))
        sources = tuple(_source(item, f"sources[{index}]") for index, item in enumerate(_list(raw, "sources")))
        fallbacks_raw = raw.get("fallbacks", {})
        if not isinstance(fallbacks_raw, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in fallbacks_raw.items()
        ):
            raise DataError("fallbacks must map each subject to a sentence")
        known = raw.get("known_names", [])
        if not isinstance(known, list) or not all(isinstance(name, str) for name in known):
            raise DataError("known_names must be a list of text values")
        checks = raw.get("checks", {})
        if not isinstance(checks, dict) or not all(key in _CHECKS and isinstance(on, bool) for key, on in checks.items()):
            raise DataError(f"checks may only switch {', '.join(_CHECKS)} on or off")
        policy = Policy(
            **{name: bool(checks.get(name, True)) for name in _CHECKS},
            known_names=tuple(str(name) for name in known),
        )
        locale = raw.get("locale")
        if locale is not None and locale not in ("es", "en", "auto"):
            raise DataError('locale must be "es", "en" or "auto"')
    except (TypeError, ValueError) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(str(exc)) from exc
    return Data(
        facts=facts,
        labels=labels,
        sources=sources,
        fallbacks={str(key): str(value) for key, value in fallbacks_raw.items()},
        policy=policy,
        locale=locale if isinstance(locale, str) else None,
    )


def _list(raw: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DataError(f"{key} must be a list of objects")
    return [{str(k): v for k, v in item.items()} for item in value]


def _text(item: Mapping[str, object], key: str, where: str, *, required: bool = False) -> str:
    value = item.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise DataError(f"{where}.{key} must be text")
    return value


def _number(value: object, where: str) -> Number:
    # A file read here gives Decimal; data passed as an object (the MCP server)
    # gives int or float. A float keeps its shortest form: -3.2 stays -3.2.
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise DataError(f"{where} must be a number")
    return value


def _fact(item: Mapping[str, object], where: str) -> Fact:
    allowed = {"name", "value", "unit", "decimals", "label", "subject", "change", "signed", "compact"}
    if set(item) - allowed:
        raise DataError(f"{where} has unknown keys: {', '.join(sorted(set(item) - allowed))}")
    subject = item.get("subject", [])
    if isinstance(subject, str):
        subject = [subject]
    if not isinstance(subject, list) or not all(isinstance(word, str) for word in subject):
        raise DataError(f"{where}.subject must be text or a list of text")
    decimals = item.get("decimals")
    if decimals is not None and (isinstance(decimals, bool) or not isinstance(decimals, int)):
        raise DataError(f"{where}.decimals must be an integer")
    flags = {}
    for flag in ("change", "signed", "compact"):
        value = item.get(flag, False)
        if not isinstance(value, bool):
            raise DataError(f"{where}.{flag} must be true or false")
        flags[flag] = value
    try:
        return Fact(
            name=_text(item, "name", where, required=True),
            value=_number(item.get("value"), f"{where}.value"),
            unit=_text(item, "unit", where),
            decimals=decimals,
            label=_text(item, "label", where),
            subject=tuple(str(word) for word in subject),
            change=flags["change"],
            signed=flags["signed"],
            compact=flags["compact"],
        )
    except (TypeError, ValueError) as exc:
        raise DataError(f"{where}: {exc}") from exc


def _label(item: Mapping[str, object], where: str, facts: Mapping[str, Fact]) -> Label:
    name = _text(item, "name", where, required=True)
    if "from" not in item:
        return Label(name, _text(item, "text", where, required=True), _text(item, "rule", where))
    source = _text(item, "from", where, required=True)
    if source not in facts:
        raise DataError(f"{where}.from names no fact: {source!r}")
    thresholds = item.get("thresholds")
    if not isinstance(thresholds, list) or not all(
        isinstance(pair, (list, tuple)) and len(pair) == 2 and isinstance(pair[1], str) for pair in thresholds
    ):
        raise DataError(f"{where}.thresholds must be a list of [bound, text] pairs")
    pairs = [(_number(pair[0], f"{where}.thresholds"), str(pair[1])) for pair in thresholds]
    try:
        return classify(name, facts[source].value, pairs, otherwise=_text(item, "otherwise", where, required=True))
    except ValueError as exc:
        raise DataError(f"{where}: {exc}") from exc


def _source(item: Mapping[str, object], where: str) -> Source:
    allowed = {"id", "text", "title", "name", "fallback"}
    if set(item) - allowed:
        raise DataError(f"{where} has unknown keys: {', '.join(sorted(set(item) - allowed))}")
    try:
        return Source(
            id=_text(item, "id", where, required=True),
            text=_text(item, "text", where, required=True),
            title=_text(item, "title", where),
            name=_text(item, "name", where),
            fallback=_text(item, "fallback", where),
        )
    except (TypeError, ValueError) as exc:
        raise DataError(f"{where}: {exc}") from exc
