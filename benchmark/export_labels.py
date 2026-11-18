"""The labeling page's documents as the flat list evaluate.py reads: one row per labeled sentence.

The page keeps one document per person and report, at
labels/<person>/items/<phase>~<report>, with every sentence's label inside.
Saved to disk (one JSON file per document, under any folder), they become
benchmark/labels/<phase>.json:

    python -m benchmark.export_labels --split pilot --from .tmp/labels-dump
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = HERE / "labels"


def _body(doc: Mapping[str, object]) -> Mapping[str, object]:
    """The document itself, whether saved bare or inside a {"data": ...} wrapper."""
    inner = doc.get("data")
    if "sentences" not in doc and isinstance(inner, dict):
        return {str(key): value for key, value in inner.items()}
    return doc


def flatten(doc: Mapping[str, object], split: str) -> list[dict[str, object]]:
    """One row per sentence with a verdict, from one person's document for one report."""
    body = _body(doc)
    if body.get("bundle") != split:
        return []
    sentences = body.get("sentences")
    if not isinstance(sentences, dict):
        return []
    rows: list[dict[str, object]] = []
    for index, label in sorted(sentences.items(), key=lambda pair: int(pair[0])):
        if not isinstance(label, dict) or not label.get("verdict"):
            continue
        types = label.get("types")
        rows.append({
            "item": body["item"],
            "sentence": int(index),
            "labeler": body["labeler"],
            "verdict": label["verdict"],
            "types": list(types) if isinstance(types, list) else [],
            "computed": label.get("computed") is True,
            "doubtful": label.get("doubtful") is True,
            "note": str(label.get("note") or ""),
        })
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=("pilot", "main"), default="pilot")
    parser.add_argument("--from", dest="source", type=Path, required=True, help="the folder with the saved documents")
    args = parser.parse_args(argv)
    rows: list[dict[str, object]] = []
    for path in sorted(args.source.rglob("*.json")):
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            rows.extend(flatten({str(key): value for key, value in raw.items()}, args.split))
    rows.sort(key=lambda row: (str(row["labeler"]), str(row["item"]), int(str(row["sentence"]))))
    LABELS.mkdir(parents=True, exist_ok=True)
    target = LABELS / f"{args.split}.json"
    target.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    people = len({row["labeler"] for row in rows})
    print(f"{len(rows)} labeled sentences from {people} people in {target.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
