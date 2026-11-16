"""Every example in examples/ is judged the way the README says.

Each folder holds a data file, a text written with figures typed in and a
draft with placeholders. What each one should show is pinned here, so an
example can never quietly stop showing it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination import compose, verify
from antihallucination.data import load_data

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _run(name: str, mode: str):
    data = load_data(_EXAMPLES / name / "data.json")
    file = "written_by_an_ai.txt" if mode == "verify" else "draft.txt"
    text = (_EXAMPLES / name / file).read_text(encoding="utf-8")
    run = verify if mode == "verify" else compose
    return run(
        text, data.facts, data.labels, data.sources,
        fallbacks=data.fallbacks, policy=data.policy, locale=data.locale or "en",
    )


@pytest.mark.parametrize(
    ("name", "mode", "actions", "text"),
    [
        (
            "saas", "verify", ["replaced", "kept", "replaced"],
            "MRR was 48,200 USD (+6.1%). Churn fell to 2.3%. 37 new customers joined.",
        ),
        (
            "saas", "compose", ["kept", "kept", "dropped"],
            "In October 2026, MRR reached 48,200 USD, strong growth of +6.1% on the previous month. "
            "Churn fell 0.4 pp to 2.3%, and 37 new customers joined.",
        ),
        (
            "support", "verify", ["replaced", "kept", "kept"],
            'Ticket 4821: "Checkout fails for EU cards" [t1]. Two business customers in Spain received '
            "invoices with the wrong VAT [t2]. There are 14 open tickets.",
        ),
        (
            "support", "compose", ["kept", "kept", "kept"],
            "Card payments failed at checkout for 23 customers in Germany and France until the release was "
            "rolled back [t1]. Two business customers in Spain were invoiced with 21% VAT instead of the "
            "reverse charge [t2]. 14 remain open.",
        ),
        (
            "sales", "verify", ["replaced", "replaced", "kept"],
            "Las ventas fueron 1.250 unidades (-3,2 %). Se sumaron 48 clientes nuevos. "
            "El ticket medio fue de 86,40 USD.",
        ),
        (
            "sales", "compose", ["kept", "kept", "dropped"],
            "En el tercer trimestre de 2026, las ventas cayeron 3,2 % hasta 1.250 unidades, una caída leve. "
            "Se sumaron 48 clientes y el ticket medio fue de 86,40 USD.",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and len(value) < 10 else None,
)
def test_each_example_shows_what_it_says(name: str, mode: str, actions: list[str], text: str) -> None:
    result = _run(name, mode)

    assert [decision.action for decision in result.decisions] == actions
    assert result.text == text


def test_the_invented_figures_are_the_ones_caught() -> None:
    """The SaaS text invents 8% and $49,000; the ticket summary turns 23 customers into 32."""
    saas = _run("saas", "verify")
    support = _run("support", "verify")

    assert [(f.check, f.span) for f in saas.decisions[0].findings][:2] == [
        ("unbacked_number", "8%"),
        ("unbacked_number", "49,000"),
    ]
    assert ("unbacked_number", "32") in [(f.check, f.span) for f in support.findings]
