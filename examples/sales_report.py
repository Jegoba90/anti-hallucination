"""The method outside crypto: a quarterly sales report where the AI only writes.

Usage:
    python examples/sales_report.py

No API key and no network. Your code computes the numbers and decides the
verdicts; the writer puts them into words with placeholders; Python writes
every figure, checks every sentence and keeps a receipt.

The two texts below were written by hand to show what a model returns. To have
a real model write the report, with the same data in a JSON file:

    python -m antihallucination write --data examples/sales/data.json --brief "Resumen trimestral"

The checks do not change with the writer.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from antihallucination import (
    Fact,
    Label,
    Result,
    classify,
    compose,
    replay,
    verify,
    verify_receipt,
)

# ── 1. Your numbers, computed by your code ────────────────────────────────────
units_previous_quarter = 1291
units_this_quarter = 1250
revenue_this_quarter = 108_000.00
new_customers = 48
change_pct = (units_this_quarter - units_previous_quarter) / units_previous_quarter * 100

FACTS = [
    Fact("ventas", units_this_quarter, unit="unidades", label="unidades vendidas", subject="ventas"),
    Fact(
        "variacion_ventas", change_pct, unit="%", decimals=1, change=True, subject="ventas",
        label="variación contra el trimestre anterior",
    ),
    Fact("clientes_nuevos", new_customers, unit="clientes", subject="clientes", label="clientes nuevos"),
    Fact(
        "ticket_medio", revenue_this_quarter / units_this_quarter, unit="USD", decimals=2,
        subject="ticket", label="ticket medio",
    ),
]

# ── 2. Your verdicts, decided by your rules ───────────────────────────────────
LABELS = [
    Label("periodo", "tercer trimestre de 2026"),
    classify(
        "tendencia_ventas", change_pct,
        [(-5, "caída fuerte"), (-1, "caída leve"), (1, "estabilidad"), (5, "subida leve")],
        otherwise="subida fuerte",
    ),
]

# What goes out when a sentence about a subject fails: written by you.
FALLBACKS = {
    "ventas": "Las ventas fueron {ventas} ({variacion_ventas}).",
    "clientes": "Se sumaron {clientes_nuevos} nuevos.",
}

# ── 3. What a writer returns ──────────────────────────────────────────────────
DRAFT = (
    "En el {periodo}, las ventas cayeron {variacion_ventas:abs} hasta {ventas}, una {tendencia_ventas}. "
    "Se sumaron {clientes_nuevos} y el ticket medio fue de {ticket_medio}. "
    "Sin duda, el próximo trimestre será mejor."
)
# The same report as another AI wrote it, figures typed in.
FREE_TEXT = (
    "En el tercer trimestre de 2026, las ventas crecieron un 5 % hasta 1.300 unidades. "
    "Se sumaron 48 clientes nuevos gracias a la campaña de Instagram. "
    "El ticket medio fue de 86,40 USD."
)

_MARK = {"kept": "✓ publicada ", "replaced": "↺ reemplazada", "dropped": "✗ quitada   "}


def show(title: str, result: Result) -> None:
    print(f"\n{title}\n")
    for decision in result.decisions:
        print(f"  {_MARK[decision.action]}  {decision.input}")
        for finding in decision.findings:
            print(f"                   · {finding.check}: {finding.detail}")
    print(f"\n  Texto final:\n    {result.text}\n")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    composed = compose(DRAFT, FACTS, LABELS, fallbacks=FALLBACKS, locale="es")
    show("1) La IA redacta con marcadores y Python escribe las cifras", composed)

    audited = verify(FREE_TEXT, FACTS, LABELS, fallbacks=FALLBACKS, locale="es")
    show("2) Auditoría de un texto que otra IA escribió con cifras", audited)

    print("3) El recibo de la auditoría\n")
    print(f"  digest:          {audited.receipt.digest}")
    print(f"  verify_receipt:  {verify_receipt(audited.receipt).status.value}")
    print(f"  replay:          {replay(audited.receipt).status.value}")
    print("\n  El digest no tiene clave: muestra que el recibo no cambió, no quién lo emitió.\n")


if __name__ == "__main__":
    main()
