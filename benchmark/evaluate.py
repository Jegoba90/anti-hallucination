"""The metrics: what the checks decided against what people said, sentence by sentence.

For each labeled report it runs verify() with the report's data, as a team
would, and lines decision i up with label i (the page cut the sentences the
same way). A sentence labeled "error" is a positive; "correct", a negative;
"neutral" is counted apart, because the checks cut a sentence with no data on
purpose. Three systems are measured on the same sentences:

    layer         verify() with every check on, the default
    numbers_only  only the figure checks, to see what the other checks add
    naive         flags a sentence with any digits not written in the data: the floor

Recall, precision and false alarms come with 95 % intervals from resampling
whole reports. With labels from two people, it also gives their agreement.

    python -m benchmark.evaluate --split pilot              # benchmark/labels/pilot.json
    python -m benchmark.evaluate --split pilot --labeler ana@example.com
"""

import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from antihallucination import Policy, verify
from antihallucination.data import Data, parse_data

from .labeling_bundle import LABELING, sentences
from .make_datasets import describe, load_datasets
from .taxonomy import GROUP_OF, TYPE_IDS, VERDICTS

HERE = Path(__file__).resolve().parent
LABELS = HERE / "labels"
RESULTS = HERE / "results"
SYSTEMS = ("layer", "numbers_only", "naive")
RESAMPLES = 2000
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class Label:
    verdict: str
    types: frozenset[str]
    computed: bool
    doubtful: bool


@dataclass(frozen=True)
class Row:
    """One labeled sentence and what each system decided about it."""

    item: str
    index: int
    sentence: str
    model: str
    variant: str
    domain: str
    locale: str
    label: Label
    flagged: Mapping[str, bool]
    checks: tuple[str, ...]


def _object(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SystemExit(f"{what} is not a JSON object")
    return {str(key): item for key, item in value.items()}


def read_labels(path: Path) -> dict[tuple[str, int], dict[str, Label]]:
    """(report, sentence) -> labeler -> label, from the page's export."""
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"{path} must hold a list of labels")
    labels: dict[tuple[str, int], dict[str, Label]] = defaultdict(dict)
    for entry in raw:
        doc = _object(entry, "a label")
        verdict = str(doc.get("verdict", ""))
        if verdict not in VERDICTS:
            continue  # started and left without a verdict
        types = doc.get("types")
        chosen = frozenset(str(t) for t in types if str(t) in TYPE_IDS) if isinstance(types, list) else frozenset()
        index = doc.get("sentence")
        if not isinstance(index, int):
            raise SystemExit(f"a label has no sentence number: {doc}")
        labels[(str(doc["item"]), index)][str(doc["labeler"])] = Label(
            verdict, chosen if verdict == "error" else frozenset(), doc.get("computed") is True,
            doc.get("doubtful") is True,
        )
    return labels


def _numbers_only(data: Data) -> Policy:
    return Policy(numbers=True, names=False, directions=False, forecasts=False, certainty=False, causes=False,
                  anchored=False, known_names=data.policy.known_names)


def _naive(sentence: str, written: str) -> bool:
    return any(token not in written for token in _DIGITS.findall(sentence))


def rows(split: str, labels: Mapping[tuple[str, int], Mapping[str, Label]], labeler: str) -> list[Row]:
    """Every sentence the labeler labeled, with the decisions of each system."""
    keys = _object(json.loads((LABELING / f"{split}-keys.json").read_text(encoding="utf-8")), "the keys")
    datasets = {str(d["id"]): d for d in load_datasets(split)}
    out: list[Row] = []
    for item, key in sorted(keys.items()):
        meta = _object(key, "a key")
        mine = {index: by[labeler] for (ident, index), by in labels.items() if ident == item and labeler in by}
        if not mine:
            continue
        record = _object(json.loads((HERE / str(meta["file"])).read_text(encoding="utf-8")), "a text")
        text = str(record["text"])
        dataset = datasets[str(meta["dataset"])]
        data = parse_data(_object(dataset["data"], "data"))
        locale = str(dataset["locale"])
        written = describe(dataset)
        cut = sentences(text)
        layer = verify(text, data.facts, data.labels, data.sources, policy=data.policy, locale=locale)
        numbers = verify(text, data.facts, data.labels, data.sources, policy=_numbers_only(data), locale=locale)
        if len(layer.decisions) != len(cut):
            raise SystemExit(f"{item}: verify() cut {len(layer.decisions)} sentences, the page {len(cut)}")
        for index, label in sorted(mine.items()):
            if index >= len(cut):
                raise SystemExit(f"{item}: label for sentence {index}, but the report has {len(cut)}")
            decision = layer.decisions[index]
            out.append(Row(
                item=item, index=index, sentence=cut[index], model=str(meta["model"]), variant=str(meta["variant"]),
                domain=str(dataset["domain"]), locale=locale, label=label,
                flagged={"layer": bool(decision.findings), "numbers_only": bool(numbers.decisions[index].findings),
                         "naive": _naive(cut[index], written)},
                checks=tuple(sorted({finding.check for finding in decision.findings})),
            ))
    return out


@dataclass(frozen=True)
class Counts:
    caught: int = 0  # errors flagged
    missed: int = 0  # errors not flagged
    alarms: int = 0  # correct sentences flagged
    passed: int = 0  # correct sentences not flagged
    neutral_cut: int = 0
    neutral_kept: int = 0

    def add(self, row: Row, system: str) -> "Counts":
        flagged = row.flagged[system]
        verdict = row.label.verdict
        return Counts(
            self.caught + (verdict == "error" and flagged), self.missed + (verdict == "error" and not flagged),
            self.alarms + (verdict == "correct" and flagged), self.passed + (verdict == "correct" and not flagged),
            self.neutral_cut + (verdict == "neutral" and flagged), self.neutral_kept + (verdict == "neutral" and not flagged),
        )


def count(selected: Iterable[Row], system: str) -> Counts:
    total = Counts()
    for row in selected:
        total = total.add(row, system)
    return total


def _ratio(top: int, bottom: int) -> float | None:
    return top / bottom if bottom else None


def metrics(counts: Counts) -> dict[str, float | int | None]:
    recall = _ratio(counts.caught, counts.caught + counts.missed)
    precision = _ratio(counts.caught, counts.caught + counts.alarms)
    f1 = 2 * recall * precision / (recall + precision) if recall and precision else None
    return {
        "errors": counts.caught + counts.missed,
        "correct": counts.alarms + counts.passed,
        "neutral": counts.neutral_cut + counts.neutral_kept,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "false_alarm_rate": _ratio(counts.alarms, counts.alarms + counts.passed),
        "neutral_cut_rate": _ratio(counts.neutral_cut, counts.neutral_cut + counts.neutral_kept),
    }


def interval(data: Sequence[Row], system: str, measure: Callable[[Counts], float | None],
             resamples: int = RESAMPLES, seed: int = 7) -> tuple[float, float] | None:
    """A 95 % interval from resampling whole reports, as the sentences of one report are not independent."""
    by_item: dict[str, list[Row]] = defaultdict(list)
    for row in data:
        by_item[row.item].append(row)
    items = sorted(by_item)
    if len(items) < 2:
        return None
    per_item = {item: count(by_item[item], system) for item in items}
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(resamples):
        total = Counts()
        for _ in items:
            part = per_item[rng.choice(items)]
            total = Counts(total.caught + part.caught, total.missed + part.missed, total.alarms + part.alarms,
                           total.passed + part.passed, total.neutral_cut + part.neutral_cut,
                           total.neutral_kept + part.neutral_kept)
        value = measure(total)
        if value is not None:
            values.append(value)
    if not values:
        return None
    values.sort()
    return values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]


def _recall(counts: Counts) -> float | None:
    return _ratio(counts.caught, counts.caught + counts.missed)


def _precision(counts: Counts) -> float | None:
    return _ratio(counts.caught, counts.caught + counts.alarms)


def _false_alarms(counts: Counts) -> float | None:
    return _ratio(counts.alarms, counts.alarms + counts.passed)


def kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    """Cohen's kappa between two people's verdicts on the same sentences."""
    if not pairs:
        return None
    observed = sum(a == b for a, b in pairs) / len(pairs)
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[k] * second[k] for k in set(first) | set(second)) / len(pairs) ** 2
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def agreement(labels: Mapping[tuple[str, int], Mapping[str, Label]], labeler: str) -> dict[str, object]:
    """How much the main labeler agrees with each other person, on the sentences both labeled."""
    others = sorted({who for by in labels.values() for who in by} - {labeler})
    result: dict[str, object] = {}
    for other in others:
        pairs = [(by[labeler], by[other]) for by in labels.values() if labeler in by and other in by]
        verdicts = [(a.verdict, b.verdict) for a, b in pairs]
        binary = [("error" if a == "error" else "ok", "error" if b == "error" else "ok") for a, b in verdicts]
        both_error = [(a, b) for a, b in pairs if a.verdict == b.verdict == "error"]
        result[other] = {
            "sentences": len(pairs),
            "verdict_agreement": _ratio(sum(a == b for a, b in verdicts), len(verdicts)),
            "kappa": kappa(verdicts),
            "kappa_error_or_not": kappa(binary),
            "same_types_when_both_say_error": _ratio(sum(a.types == b.types for a, b in both_error), len(both_error)),
        }
    return result


def breakdown(data: Sequence[Row], key: Callable[[Row], str]) -> dict[str, dict[str, float | int | None]]:
    groups: dict[str, list[Row]] = defaultdict(list)
    for row in data:
        groups[key(row)].append(row)
    return {name: metrics(count(groups[name], "layer")) for name in sorted(groups)}


def by_type(data: Sequence[Row]) -> dict[str, dict[str, float | int | None]]:
    """Recall of the checks for each kind of error people found (a sentence counts once per kind it has)."""
    out: dict[str, dict[str, float | int | None]] = {}
    for kind in TYPE_IDS:
        having = [row for row in data if kind in row.label.types]
        if having:
            caught = sum(row.flagged["layer"] for row in having)
            out[kind] = {"sentences": len(having), "recall": caught / len(having)}
    for group in sorted(set(GROUP_OF.values())):
        having = [row for row in data if any(GROUP_OF[kind] == group for kind in row.label.types)]
        if having:
            out[f"group:{group}"] = {"sentences": len(having),
                                     "recall": sum(row.flagged["layer"] for row in having) / len(having)}
    return out


def report(split: str, labeler: str | None = None, path: Path | None = None) -> dict[str, object]:
    labels = read_labels(path or LABELS / f"{split}.json")
    people = Counter(who for by in labels.values() for who in by)
    if not people:
        raise SystemExit("no labels yet")
    main_labeler = labeler or people.most_common(1)[0][0]
    data = rows(split, labels, main_labeler)
    systems: dict[str, object] = {}
    for system in SYSTEMS:
        values: dict[str, object] = dict(metrics(count(data, system)))
        values["recall_95"] = interval(data, system, _recall)
        values["precision_95"] = interval(data, system, _precision)
        values["false_alarm_rate_95"] = interval(data, system, _false_alarms)
        systems[system] = values
    alarms = Counter(check for row in data if row.label.verdict == "correct" and row.flagged["layer"]
                     for check in row.checks)
    computed = [row for row in data if row.label.verdict == "correct" and row.label.computed]
    return {
        "split": split,
        "labeler": main_labeler,
        "reports": len({row.item for row in data}),
        "sentences": len(data),
        "doubtful": sum(row.label.doubtful for row in data),
        "systems": systems,
        "by_type": by_type(data),
        "by_model": breakdown(data, lambda row: row.model),
        "by_variant": breakdown(data, lambda row: row.variant),
        "by_locale": breakdown(data, lambda row: row.locale),
        "by_domain": breakdown(data, lambda row: row.domain),
        "checks_on_correct_sentences": dict(alarms.most_common()),
        "computed_by_the_model": {"sentences": len(computed),
                                  "flagged": sum(row.flagged["layer"] for row in computed)},
        "agreement": agreement(labels, main_labeler),
    }


def _pct(value: object) -> str:
    return f"{value * 100:.1f} %" if isinstance(value, float) else "–"


def _span(value: object) -> str:
    if isinstance(value, tuple) and len(value) == 2:
        return f"{value[0] * 100:.0f}–{value[1] * 100:.0f}"
    return "–"


def summary(result: Mapping[str, object]) -> str:
    lines = [f"{result['split']}: {result['reports']} reports, {result['sentences']} sentences "
             f"labeled by {result['labeler']}", "",
             "| System | Errors caught (recall) | Precision | False alarms on correct | Neutral cut |",
             "|---|---|---|---|---|"]
    systems = result["systems"]
    if isinstance(systems, dict):
        for name, values in systems.items():
            if isinstance(values, dict):
                lines.append(
                    f"| {name} | {_pct(values['recall'])} ({_span(values['recall_95'])}) | "
                    f"{_pct(values['precision'])} ({_span(values['precision_95'])}) | "
                    f"{_pct(values['false_alarm_rate'])} ({_span(values['false_alarm_rate_95'])}) | "
                    f"{_pct(values['neutral_cut_rate'])} |"
                )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=("pilot", "main"), default="pilot")
    parser.add_argument("--labeler", help="whose labels are the truth; by default, whoever labeled most")
    parser.add_argument("--labels", type=Path, help="the labels file, if not benchmark/labels/<split>.json")
    args = parser.parse_args(argv)
    result = report(args.split, args.labeler, args.labels)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{args.split}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    print(summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
