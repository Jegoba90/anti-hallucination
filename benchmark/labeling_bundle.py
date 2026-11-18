"""The labeling page's bundle: every report with its data, cut into the sentences the package decides on.

The page shows each report next to its data, sentence by sentence, without
the model that wrote it or what the checks decided: the labels must not know.
The sentences are cut with the package's own split_lines and split_sentences,
so label i is about decision i of verify(). Reports go in a fixed shuffled
order, and a share of them is marked for the second person, to measure how
much two people agree.

    python -m benchmark.labeling_bundle --split pilot     # benchmark/labeling/pilot.json and pilot-keys.json

The keys file says which model and prompt wrote each report; the page never
loads it.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from antihallucination.text import split_lines, split_sentences

from .make_datasets import describe_parts, load_datasets
from .taxonomy import GROUPS, TYPES
from .generate_texts import TEXTS

HERE = Path(__file__).resolve().parent
LABELING = HERE / "labeling"


def sentences(text: str) -> list[str]:
    """The text's sentences, cut exactly as verify() cuts them."""
    return [sentence for line in split_lines(text) for sentence in split_sentences(line)]


def item_id(dataset: str, model: str) -> str:
    """A short opaque id: the page shows it, and it does not say which model wrote the report."""
    return hashlib.sha256(f"{dataset}|{model}".encode("utf-8")).hexdigest()[:8]


def _share(ident: str, salt: str) -> float:
    """A number in [0, 1) fixed by the id, for a shuffle and a sample nobody chose by hand."""
    return int(hashlib.sha256(f"{salt}|{ident}".encode("utf-8")).hexdigest()[:8], 16) / 2**32


def build(split: str, overlap: float) -> tuple[dict[str, object], dict[str, object]]:
    """The bundle for the page and the keys that stay out of it."""
    datasets = {str(d["id"]): d for d in load_datasets(split)}
    items: list[dict[str, object]] = []
    keys: dict[str, object] = {}
    for path in sorted((TEXTS / split).glob("*/*.json")):
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            continue
        dataset = datasets[str(raw["dataset"])]
        ident = item_id(str(raw["dataset"]), str(raw["model"]))
        text = str(raw["text"])
        items.append({"id": ident, "data": describe_parts(dataset), "text": text, "sentences": sentences(text),
                      "overlap": _share(ident, "overlap") < overlap})
        keys[ident] = {"dataset": raw["dataset"], "model": raw["model"], "variant": raw["variant"],
                       "split": dataset["split"], "file": path.relative_to(HERE).as_posix()}
    items.sort(key=lambda item: _share(str(item["id"]), "order"))
    bundle: dict[str, object] = {
        "name": split,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "types": [{"id": ident, "name": name, "group": group, "help": help_text} for ident, name, group, help_text in TYPES],
        "groups": GROUPS,
        "items": items,
    }
    return bundle, keys


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=("pilot", "main"), default="pilot")
    parser.add_argument("--overlap", type=float, default=0.25, help="share of reports for the second person")
    args = parser.parse_args(argv)
    bundle, keys = build(args.split, args.overlap)
    items = bundle["items"]
    if not isinstance(items, list) or not items:
        print(f"no texts in {TEXTS / args.split}: run benchmark.generate_texts first", file=sys.stderr)
        return 1
    LABELING.mkdir(parents=True, exist_ok=True)
    (LABELING / f"{args.split}.json").write_text(json.dumps(bundle, ensure_ascii=False) + "\n", encoding="utf-8")
    (LABELING / f"{args.split}-keys.json").write_text(json.dumps(keys, ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8")
    count = sum(len(item["sentences"]) for item in items if isinstance(item, dict) and isinstance(item["sentences"], list))
    overlap = sum(1 for item in items if isinstance(item, dict) and item["overlap"])
    print(f"{len(items)} reports, {count} sentences, {overlap} reports for the second person")
    return 0


if __name__ == "__main__":
    sys.exit(main())
