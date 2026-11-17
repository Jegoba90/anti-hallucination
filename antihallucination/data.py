"""Your facts, labels, sources and rules in one JSON file, for the command line.

    {
      "locale": "es",
      "facts": [
        {"name": "ventas", "value": 1250, "unit": "unidades", "subject": "ventas"},
        {"name": "variacion_ventas", "value": -3.2, "unit": "%", "decimals": 1,
         "change": true, "subject": "ventas"},
        {"name": "ventas_anteriores", "value": 1291, "unit": "unidades", "subject": "ventas"},
        {"name": "cambio_ventas", "compute": "difference",
         "from": "ventas_anteriores", "to": "ventas"}
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

A fact with "compute" ("percent_change" or "difference") has no value: it is
computed from the facts named in "from" and "to", the same as
percent_change() and difference(), and takes its unit from them: a "unit"
given must be that one.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import NoReturn

from .checks import Policy
from .facts import COMPUTE, Fact, Label, Number, Source, classify, difference, percent_change

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
        facts = _facts(_list(raw, "facts"))
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


def _facts(items: list[dict[str, object]]) -> tuple[Fact, ...]:
    """The facts in the order given; a computed one waits for the facts it is computed from.

    They are built in rounds: first the facts given, then, each round, the
    computed facts whose two facts were built in an earlier round, in the
    order given. A round looks only at the facts the last one unblocked, so
    a long chain listed backwards costs its length, not its length squared.
    """
    built: dict[int, Fact] = {}
    ready: dict[str, Fact] = {}  # the facts built in earlier rounds, by name
    unbuilt = set(range(len(items)))
    waiting_on: dict[str, list[int]] = {}  # name -> the computed facts that need it
    for index, item in enumerate(items):
        if "compute" in item:
            for key in ("from", "to"):
                value = item.get(key)
                if isinstance(value, str):
                    waiting_on.setdefault(value, []).append(index)
    this_round = [index for index, item in enumerate(items) if "compute" not in item]
    while unbuilt:
        if not this_round:
            _unresolved(items, min(unbuilt))
        for index in this_round:
            built[index] = _fact(items[index], f"facts[{index}]", ready)
        unbuilt.difference_update(this_round)
        unblocked: set[int] = set()
        for index in this_round:
            name = built[index].name
            if name not in ready:
                unblocked.update(waiting_on.get(name, ()))
            ready[name] = built[index]
        this_round = sorted(
            index
            for index in unblocked
            if index in unbuilt and all(_names_one_of(items[index].get(key), ready) for key in ("from", "to"))
        )
    return tuple(built[index] for index in range(len(items)))


def _names_one_of(value: object, facts: Mapping[str, Fact]) -> bool:
    return isinstance(value, str) and value in facts


def _unresolved(items: list[dict[str, object]], index: int) -> NoReturn:
    """Why facts[index] cannot be computed: a name that is no fact, itself, or a loop."""
    names = {item.get("name") for item in items}
    for key in ("from", "to"):
        value = items[index].get(key)
        if not isinstance(value, str):
            raise DataError(f"facts[{index}].{key} must be the name of a fact")
        if value not in names:
            raise DataError(f"facts[{index}].{key} names no fact: {value!r}")
        if value == items[index].get("name"):
            raise DataError(f"facts[{index}].{key}: a fact cannot be computed from itself")
    raise DataError(f"facts[{index}] is computed from facts that are computed from it")


def _fact(item: Mapping[str, object], where: str, ready: Mapping[str, Fact]) -> Fact:
    allowed = {"name", "value", "unit", "decimals", "label", "subject", "change", "signed", "compact"}
    if "compute" in item:
        allowed = (allowed - {"value"}) | {"compute", "from", "to"}
        if "value" in item:
            raise DataError(f"{where}.value: a computed fact takes no value; it is computed from its from and to facts")
    elif "from" in item or "to" in item:
        raise DataError(f'{where} has from and to but no compute ("percent_change" or "difference")')
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
    if "compute" in item:
        compute = item["compute"]
        if compute not in COMPUTE:
            raise DataError(f'{where}.compute must be "percent_change" or "difference"')
        if item.get("change", True) is not True:
            raise DataError(f"{where}.change: a computed fact is always a change")
        build = partial(
            percent_change if compute == "percent_change" else difference,
            _text(item, "name", where, required=True),
            ready[str(item["from"])],
            ready[str(item["to"])],
            label=_text(item, "label", where),
            subject=tuple(str(word) for word in subject) or None,
            signed=flags["signed"],
            compact=flags["compact"],
        )
        try:
            # No decimals given: the default of each, one for a percent change.
            computed = build() if decimals is None else build(decimals=decimals)
        except (TypeError, ValueError) as exc:
            raise DataError(f"{where}: {exc}") from exc
        # A unit may be repeated, as a model often does, but not changed.
        unit = _text(item, "unit", where)
        if "unit" in item and unit.strip() != computed.unit:
            raise DataError(f"{where}.unit: this change is in «{computed.unit}», the unit its from and to facts give")
        return computed
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
