"""The evaluation's own tools: the data sets, the prompts, the labeling bundle and the metrics.

The models are not called here: these pin what the evaluation is built on, so
a change to the package or to the scripts cannot quietly move its numbers.
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import verify
from antihallucination.data import parse_data
from benchmark import evaluate, export_labels, make_datasets
from benchmark.generate_texts import prompt, variant
from benchmark.labeling_bundle import item_id, sentences


def test_the_data_sets_match_the_script() -> None:
    # The same seed gives the same files on every Python the CI runs.
    assert make_datasets.main(["--check"]) == 0


def test_every_data_set_reads_and_the_splits_are_balanced() -> None:
    pilot, main = make_datasets.load_datasets("pilot"), make_datasets.load_datasets("main")

    for dataset in pilot + main:
        parse_data(dataset["data"])  # type: ignore[arg-type]
        assert make_datasets.describe(dataset)
    assert len(pilot) == 20 and len(main) == 100
    assert set(Counter((d["domain"], d["locale"]) for d in main).values()) == {10}
    assert Counter(d["split"] for d in main) == {"test": 70, "dev": 30}


def test_the_prompt_carries_the_data_and_the_strict_rule_only_when_strict() -> None:
    dataset = make_datasets.load_datasets("pilot")[1]  # p02: SaaS, in Spanish
    system, strict = prompt(dataset, "strict")
    _, plain = prompt(dataset, "plain")

    assert "analista" in system
    assert "4,0 %" in strict and "83.662 usuarios" in strict  # written as the package writes them
    assert "Usa solo la información de los datos" in strict
    assert "Usa solo" not in plain
    assert "sin títulos ni listas" in plain


def test_each_model_gets_half_the_data_sets_strict() -> None:
    ids = [str(d["id"]) for d in make_datasets.load_datasets("main")]

    for model in ("groq:llama-3.1-8b-instant", "groq:openai/gpt-oss-120b"):
        assert Counter(variant(ident, model) for ident in ids) == {"strict": 50, "plain": 50}


def test_the_page_cuts_the_sentences_verify_decides_on() -> None:
    text = "Resumen.\n\nLas ventas cayeron 3,2 % (vs. el trimestre anterior). El Sr. Paz firmó. [s1]\n- Otra línea"

    decisions = verify(text, locale="es").decisions

    assert sentences(text) == [decision.input for decision in decisions]


def test_an_item_id_does_not_name_the_model() -> None:
    ident = item_id("p01", "groq:llama-3.1-8b-instant")

    assert len(ident) == 8 and "llama" not in ident


@pytest.fixture
def labeled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """One report on data set p01, labeled by two people who disagree on one sentence."""
    text = "Ashgrove received 1,287 tickets. Customer satisfaction rose to 75%. Here is the summary."
    (tmp_path / "texts").mkdir()
    (tmp_path / "texts" / "r.json").write_text(json.dumps({"text": text}), encoding="utf-8")
    (tmp_path / "labeling").mkdir()
    keys = {"r1": {"dataset": "p01", "model": "groq:m", "variant": "plain", "split": "pilot", "file": "texts/r.json"}}
    (tmp_path / "labeling" / "pilot-keys.json").write_text(json.dumps(keys), encoding="utf-8")
    labels = [
        {"item": "r1", "sentence": 0, "labeler": "ana", "verdict": "correct", "types": []},
        {"item": "r1", "sentence": 1, "labeler": "ana", "verdict": "error", "types": ["wrong_figure"]},
        {"item": "r1", "sentence": 2, "labeler": "ana", "verdict": "neutral", "types": []},
        {"item": "r1", "sentence": 0, "labeler": "bea", "verdict": "correct", "types": []},
        {"item": "r1", "sentence": 1, "labeler": "bea", "verdict": "error", "types": ["wrong_figure"]},
        {"item": "r1", "sentence": 2, "labeler": "bea", "verdict": "correct", "types": []},
    ]
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(labels), encoding="utf-8")
    monkeypatch.setattr(evaluate, "HERE", tmp_path)
    monkeypatch.setattr(evaluate, "LABELING", tmp_path / "labeling")
    return path


def test_the_metrics_on_a_case_labeled_by_hand(labeled: Path) -> None:
    result = evaluate.report("pilot", "ana", labeled)
    layer = result["systems"]["layer"]  # type: ignore[index]

    assert (result["reports"], result["sentences"]) == (1, 3)
    assert (layer["errors"], layer["correct"], layer["neutral"]) == (1, 1, 1)
    assert layer["recall"] == 1.0 and layer["false_alarm_rate"] == 0.0
    assert layer["neutral_cut_rate"] == 1.0  # the checks cut a sentence with no data, by design
    assert result["by_type"]["wrong_figure"] == {"sentences": 1, "recall": 1.0}  # type: ignore[index]


def test_two_people_who_disagree_once_in_three(labeled: Path) -> None:
    agreement = evaluate.report("pilot", "ana", labeled)["agreement"]["bea"]  # type: ignore[index]

    assert agreement["sentences"] == 3
    assert agreement["verdict_agreement"] == pytest.approx(2 / 3)
    assert agreement["kappa_error_or_not"] == 1.0  # both call the same sentence an error


def test_a_page_document_becomes_one_row_per_labeled_sentence() -> None:
    doc = {"bundle": "pilot", "item": "r1", "labeler": "u_1", "sentences": {
        "1": {"verdict": "error", "types": ["invented_name"], "doubtful": True, "note": "¿quién?"},
        "0": {"verdict": "correct", "types": [], "computed": True},
        "2": {"verdict": "", "types": []},  # opened, never decided
    }}

    rows = export_labels.flatten({"data": doc}, "pilot")

    assert [(row["sentence"], row["verdict"]) for row in rows] == [(0, "correct"), (1, "error")]
    assert rows[0]["computed"] is True and rows[1]["doubtful"] is True
    assert export_labels.flatten(doc, "main") == []


def test_kappa_is_one_for_the_same_labels_and_zero_for_chance() -> None:
    assert evaluate.kappa([("a", "a"), ("b", "b")]) == 1.0
    assert evaluate.kappa([("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")]) == 0.0
