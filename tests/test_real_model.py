"""What a real model wrote on 2026-11-16, judged the same way every time.

The first test of write() with a real model (gpt-oss-120b on Groq, record in
docs/pruebas-2026-11-16.md) returned four drafts. They are kept here as the
model wrote them, so any change to the checks shows up as a change in how real
output is judged: the opinion of run 1 must stay out, and the clean drafts of
runs 2 to 4 must keep going out whole.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import compose
from antihallucination.data import load_data

_ROOT = Path(__file__).resolve().parents[1]
_RECORD = json.loads((_ROOT / "tests" / "fixtures" / "real_model" / "groq_2026-11-16.json").read_text(encoding="utf-8"))
_DATA = load_data(_ROOT / _RECORD["data"])


@pytest.mark.parametrize("run", _RECORD["runs"], ids=lambda run: f"run{run['run']}")
def test_each_real_draft_is_judged_as_recorded(run: dict) -> None:
    result = compose(
        run["draft"], _DATA.facts, _DATA.labels, _DATA.sources,
        fallbacks=_DATA.fallbacks, policy=_DATA.policy, locale="es",
    )

    assert [decision.action for decision in result.decisions] == run["actions"]
    assert result.text == run["text"]


@pytest.mark.parametrize("run", _RECORD["runs"], ids=lambda run: f"run{run['run']}")
def test_the_model_typed_no_figure(run: dict) -> None:
    """The contract held with a real model: every figure went through a placeholder."""
    without_placeholders = re.sub(r"\{[^{}]+\}", "", run["draft"])

    assert not re.search(r"\d", without_placeholders)


def test_the_opinion_of_run_one_is_cut_for_carrying_no_data() -> None:
    first = _RECORD["runs"][0]
    result = compose(first["draft"], _DATA.facts, _DATA.labels, policy=_DATA.policy, locale="es")

    assert [finding.check for finding in result.findings] == ["unanchored"]
    assert "parámetros esperados" in result.decisions[2].input
