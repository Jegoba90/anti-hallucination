"""Numbers decide; the AI only writes.

Your code computes the facts and decides the verdicts. A writer (any LLM, or a
person) puts them into words. This package fills in every figure from your
facts, checks every sentence against your facts, labels and sources, publishes
only what passes and keeps a receipt of each decision.

    from antihallucination import Fact, compose

    facts = [Fact("ventas", 1250, unit="unidades", subject="ventas"),
             Fact("variacion", -3.2, unit="%", change=True, subject="ventas")]
    result = compose("Las ventas cayeron {variacion:abs} hasta {ventas}.", facts, locale="es")
    result.text  # 'Las ventas cayeron 3,2 % hasta 1.250 unidades.'

write() asks a model for the draft (antihallucination.writers has Claude and
OpenAI-compatible writers; any function (system, prompt) -> str works) and
sends it through compose(). The model is told the placeholders, never a value.
The command line is python -m antihallucination.

What it can show: every figure in the text came from your facts (compose) or
matches them (verify), and every name is in your evidence. What it cannot:
that your facts are right, or that no sentence claims more than the lists in
lexicon.py know how to catch.
"""

__version__ = "0.4.0"

from .checks import MAX_MATCHES, Finding, Policy, TooManyMatches
from .errors import WriterError
from .core import Decision, ReplayCheck, ReplayStatus, Result, compose, replay, verify
from .facts import Derivation, Fact, Label, Source, classify, difference, percent_change
from .receipt import RECIPE, Receipt, ReceiptCheck, ReceiptStatus, verify_receipt
from .writing import Written, write

__all__ = [
    "MAX_MATCHES",
    "RECIPE",
    "__version__",
    "Decision",
    "Derivation",
    "Fact",
    "Finding",
    "Label",
    "Policy",
    "Receipt",
    "ReceiptCheck",
    "ReceiptStatus",
    "ReplayCheck",
    "ReplayStatus",
    "Result",
    "Source",
    "TooManyMatches",
    "Written",
    "WriterError",
    "classify",
    "compose",
    "difference",
    "percent_change",
    "replay",
    "verify",
    "verify_receipt",
    "write",
]
