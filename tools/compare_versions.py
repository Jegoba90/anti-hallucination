"""Compare this checkout with an earlier version: the same decisions on thousands of random inputs.

A change meant only to make the checks faster must not change what they
decide. This runs the same random texts and data through the package in this
checkout and through the package at a git ref (HEAD by default, so it checks
your uncommitted change), and compares the final text and every decision:
action, output, findings, facts, labels and sources. When both versions keep
the same receipt recipe, the receipt digests must match too.

    python tools/compare_versions.py                      # this checkout against HEAD
    python tools/compare_versions.py v0.2.1 --documents 5000 --seed 7
    python tools/compare_versions.py v0.2.2 --ignore sign_dropped

The inputs are built to reach the edges: long words, figures glued to words,
subjects with dots or no letters, facts that share a value, verdicts quoted
in the text, several sources cited at once. Computed facts are compared too
when both versions have them.

Exit 0 when every input gives the same decisions, 1 when one does not (the
first few are printed with both outcomes), 2 when the ref cannot be used.
"""

import argparse
import ast
import importlib
import io
import random
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "antihallucination"
REF_PACKAGE = "antihallucination_ref"
MASK = "￼"

WORDS = [
    # moves, both languages, some negated or not quite moves
    "subió", "subieron", "crecieron", "aumentó", "cayeron", "cayó", "bajó", "bajaron", "bajo", "baja",
    "descendió", "retrocedió", "se disparó", "al alza", "a la baja", "rose", "fell", "grew", "dropped",
    "declined", "increased", "up by", "down 3", "higher than", "lower than", "gains", "loss", "losses",
    "pérdida", "déficit", "in the red", "números rojos",
    # negators and what does not negate
    "no", "not", "sin", "ni", "never", "didn't", "didn’t", "no'", "not only", "no solo", "sólo", "only",
    # clause breaks
    ",", ":", ";", "(", ")", "—", "–", " - ", "y", "pero", "mientras", "and", "but", "while", "although",
    # figures
    "5 %", "-3,2 %", "3,2 %", "−3,2%", "+5", "1.250", "1,250", "1.300", "3.2", "86,40", "86.4", "48",
    "tres", "five", "treinta y dos", "twenty-one", "un millón", "a million", "4bn", "1,2 millones",
    "4.2 million", "Q3", "COVID-19", "5G", "2026-11-14", "12:30", "0", "2026", "1,2,3", "7", "½", "²",
    "86", "1,3 mil", "1.3 thousand", "2,50 %", "4,20 millones", "3,20 %", "0,5 %", "77",
    # words around the data, and its odder subjects and identifiers
    "ventas", "las ventas", "clientes", "ticket", "ticket medio", "revenue", "ingresos", "margen bruto",
    "margen", "márgenes", "costes", "coste", "stock", "EE.UU.", "eeuu", "unidades", "USD", "el", "la",
    "de", "en", "the", "of", "&co", "(x)", "ø-index", "S&P 500", "s&p", "ventas netas", "øø", "largo",
    "cero", "mil", "Q4", "q½", "q1½", "Q1½", "co-19",
    # names and capitals
    "Instagram", "ACME", "Acme", "S&P", "O'Brien", "McDonald", "Coca-Cola", "J.", "Smith", "Sr.",
    "etc.", "İstanbul", "Straße", "Øster", "ÉXITO", "Enero", "Monday", "KPI",
    # claims
    "subirá", "will", "clearly", "because", "gracias a", "debido a", "probablemente", "lo que refleja",
    # verdicts as written
    "caída leve", "steady", "tercer trimestre de 2026", "riesgo alto", "(a) leve", "-steady", "Riesgo Alto",
    "estable", "estables",
]  # fmt: skip
PUNCT = [".", "!", "?", "…", "...", ".\"", ".»", ".)", ". ", "?!", ".]", ""]
SPACES = [" ", " ", " ", "  ", "\t", " ", " " + MASK + " "]
PLACEHOLDERS = [
    "{ventas}", "{variacion_ventas}", "{variacion_ventas:abs}", "{variacion_ventas:signed}",
    "{margen_var:abs}", "{revenue_change}", "{tendencia}", "{estado}", "{periodo}", "{nope}",
    "{ventas:bad}", "{stock_var}", "{clientes}",
]  # fmt: skip
CITES = ["[s1]", "[s2]", "[s1, s2]", "[s3]", "[nope]", "[s1,s3]", "[s4]", "[s5, s6]", "[s4, s1]", "[s7]", "[s6,s5]"]

FACTS: list[dict[str, object]] = [
    {"name": "ventas", "value": 1250, "unit": "unidades", "subject": "ventas"},
    {"name": "variacion_ventas", "value": -3.2, "unit": "%", "change": True, "subject": "ventas"},
    {"name": "clientes", "value": 48, "unit": "clientes", "subject": "clientes"},
    {"name": "ticket", "value": 86.4, "unit": "USD", "decimals": 2, "subject": ("ticket", "ticket medio")},
    {"name": "revenue_change", "value": 5, "unit": "%", "change": True, "subject": ("revenue", "ingresos")},
    {"name": "margen_var", "value": -0.5, "unit": "%", "change": True, "subject": "margen bruto"},
    {"name": "eeuu", "value": 7, "subject": "EE.UU."},
    {"name": "stock_var", "value": 0, "change": True, "subject": "stock"},
    {"name": "ventas_otra", "value": 2.5, "unit": "%", "change": True, "subject": "ventas"},
    {"name": "grande", "value": 4200000, "compact": True, "subject": "unidades"},
    {"name": "dup_clientes", "value": 48, "unit": "clientes", "subject": "clientes nuevos"},
    # Two more falls of 3.2 %: a figure without its minus stands for three.
    {"name": "dup_caida", "value": -3.2, "unit": "%", "change": True, "subject": "margen"},
    {"name": "dup_otra", "value": -3.2, "unit": "%", "change": True, "subject": "costes"},
    {"name": "raro", "value": 12, "subject": ("&co", "(x)", "ø-index", "S&P 500", "EE.UU.", "ventas netas")},
    {"name": "sin_letras", "value": 77, "subject": "øø"},
    {"name": "largo", "value": Decimal("3.20000000000000000000000000000001"), "unit": "%", "change": True, "subject": "largo"},
    {"name": "cero", "value": 0, "subject": "cero"},
    {"name": "mil", "value": 1000, "subject": "mil"},
]
LABELS = [
    ("tendencia", "caída leve"),
    ("periodo", "tercer trimestre de 2026"),
    ("estado", "steady"),
    ("riesgo", "riesgo alto"),
    ("tendencia_otra", "caída leve"),
    ("paren", "(a) leve"),
    ("guion", "-steady"),
    ("riesgo_mayus", "Riesgo Alto"),
    ("estable", "estable"),
]
SOURCES = [
    ("s1", "Revenue rose 5% in Q3 according to ACME. Sales fell to 1,300 units."),
    ("s2", "La empresa Instagram informó 1.300 unidades y un 3,2 % menos."),
    ("s3", "Plain text with COVID-19, O'Brien and 2026, the Smiths and McDonalds, nothing moved."),
    ("s4", "Ventas cayeron 3,2 % en Q4; S&P 500 y &co, q½, q1½ y ø-index."),
    ("s5", "subieron"),
    ("s6", "x"),
    ("s7", "Coca-Cola EE.UU. 86,40 USD treinta y dos"),
]
FALLBACKS = [
    ("ventas", "Las ventas fueron {ventas}."),
    ("Ventas", "Ventas: {ventas}."),
    ("clientes", "Se sumaron {clientes}."),
    ("margen", "El margen fue {dup_caida}."),
]

Outcome = tuple[object, ...]


def _long_word(rng: random.Random) -> str:
    alphabet = rng.choice(["a", "ab", "ño", "x'y", "-", "z9"])
    return (alphabet * rng.randint(20, 200))[: rng.randint(30, 400)]


def _sentence(rng: random.Random, *, compose: bool) -> str:
    pieces: list[str] = []
    for _ in range(rng.randint(1, rng.choice([6, 15, 40, 120]))):
        roll = rng.random()
        if roll < 0.62:
            word = rng.choice(WORDS)
        elif roll < 0.72:
            word = rng.choice(PLACEHOLDERS) if compose else rng.choice(WORDS)
        elif roll < 0.78:
            word = rng.choice(CITES)
        elif roll < 0.84:
            word = _long_word(rng)
        elif roll < 0.9:
            word = rng.choice(WORDS).capitalize()
        elif roll < 0.95:
            word = rng.choice(PUNCT)
        else:
            word = rng.choice(["." * rng.randint(2, 30), " " * rng.randint(2, 50), MASK * 3, "''", "’"])
        pieces.append(word)
        # Glued pieces now and then: «(cayeron», «ventas,crecieron», «5%)».
        pieces.append("" if rng.random() < 0.2 else rng.choice(SPACES))
    text = "".join(pieces).strip()
    if rng.random() < 0.8:
        text = text[:1].upper() + text[1:]
    return text + rng.choice(PUNCT)


def _document(rng: random.Random, *, compose: bool) -> str:
    lines = [" ".join(_sentence(rng, compose=compose) for _ in range(rng.randint(1, 4))) for _ in range(rng.randint(1, 4))]
    return rng.choice(["\n", "\n\n", "\r\n", " "]).join(lines)


def _inputs(package: ModuleType, rng: random.Random) -> dict[str, object]:
    """Facts, labels, sources, policy and fallbacks for one document, built with one version's classes."""
    facts = [package.Fact(**spec) for spec in FACTS if rng.random() < 0.7]
    names = {fact.name for fact in facts}
    labels = [package.Label(name, text) for name, text in LABELS if rng.random() < 0.7 and name not in names]
    sources = [package.Source(sid, text) for sid, text in SOURCES if rng.random() < 0.6]
    subjects = {word.casefold() for fact in facts for word in fact.subjects}
    fallbacks = {
        subject: template
        for subject, template in FALLBACKS
        if subject.casefold() in subjects
        and all(name in names for name in re.findall(r"\{(\w+)", template))
        and rng.random() < 0.5
    }
    return {
        "facts": facts,
        "labels": labels,
        "sources": sources,
        "policy": package.Policy(known_names=("ACME",)) if rng.random() < 0.5 else None,
        "fallbacks": fallbacks or None,
    }


def _decisions(run: Callable[[], object], ignore: frozenset[str], digest: bool) -> Outcome:
    """What one version decided, as plain data both versions can be compared on."""
    try:
        result = run()
    except Exception as exc:  # the same error on both sides is the same outcome
        return ("error", type(exc).__name__, str(exc))
    decisions = []
    for decision in getattr(result, "decisions"):
        record = decision.to_dict()
        record["findings"] = [finding for finding in record["findings"] if finding["check"] not in ignore]
        decisions.append(record)
    receipt = getattr(result, "receipt").digest if digest else None
    return ("ok", getattr(result, "text"), decisions, receipt)


def _explain(ref: Outcome, now: Outcome) -> str:
    """Where two outcomes part: the error, the text, or the first decision that differs and how."""
    if ref[0] != "ok" or now[0] != "ok":
        return f"    ref: {str(ref)[:300]}\n    now: {str(now)[:300]}"
    lines = []
    if ref[1] != now[1]:
        lines.append(f"    text, ref: {str(ref[1])[:300]!r}\n    text, now: {str(now[1])[:300]!r}")
    ref_decisions, now_decisions = ref[2], now[2]
    assert isinstance(ref_decisions, list) and isinstance(now_decisions, list)
    if len(ref_decisions) != len(now_decisions):
        lines.append(f"    sentences, ref: {len(ref_decisions)}, now: {len(now_decisions)}")
    for index, (before, after) in enumerate(zip(ref_decisions, now_decisions)):
        if before != after:
            lines.append(f"    sentence {index}: {str(before.get('input'))[:200]!r}")
            for key in before:
                if before[key] != after.get(key):
                    lines.append(f"      {key}, ref: {str(before[key])[:300]}\n      {key}, now: {str(after.get(key))[:300]}")
            break
    if not lines and ref[3] != now[3]:
        lines.append(f"    the same decisions, but receipt digests differ: {ref[3]} / {now[3]}")
    return "\n".join(lines)


def compare_documents(old: ModuleType, new: ModuleType, rng: random.Random, count: int, ignore: frozenset[str]) -> list[str]:
    """Random documents through both versions' verify() and compose(); the differences found."""
    digest = not ignore and getattr(old, "RECIPE", None) == getattr(new, "RECIPE", None)
    differences: list[str] = []
    for _ in range(count):
        compose = rng.random() < 0.4
        text = _document(rng, compose=compose)
        seed = rng.random()
        locale = rng.choice(["es", "en"] if compose else ["es", "en", "auto"])
        outcomes = []
        for package in (old, new):
            inputs = _inputs(package, random.Random(seed))
            run = package.compose if compose else package.verify
            outcomes.append(_decisions(lambda: run(text, locale=locale, **inputs), ignore, digest))
        if outcomes[0] != outcomes[1]:
            mode = "compose" if compose else "verify"
            differences.append(f"{mode} ({locale}) {text[:200]!r}\n{_explain(outcomes[0], outcomes[1])}")
    return differences


def compare_data(old: ModuleType, new: ModuleType, rng: random.Random, count: int) -> list[str]:
    """Random lists of computed facts through both versions' parse_data: chains, loops, repeated names."""
    differences: list[str] = []
    for _ in range(count):
        size = rng.randint(0, 12)
        names = [f"f{rng.randint(0, size + 2)}" for _ in range(size)]
        items: list[dict[str, object]] = []
        for name in names:
            if rng.random() < 0.45:
                item: dict[str, object] = {"name": name, "value": rng.choice([1, 2, 5, -3, 0, 100])}
            else:
                item = {"name": name, "compute": rng.choice(["difference", "percent_change", "bogus"])}
                for key in ("from", "to"):
                    if rng.random() < 0.95:
                        item[key] = rng.choice([*names, "nope", name])
                    elif rng.random() < 0.5:
                        item[key] = 7
            if rng.random() < 0.05:
                item["value"] = "x"
            items.append(item)
        rng.shuffle(items)
        outcomes: list[Outcome] = []
        for package in (old, new):
            try:
                facts = package.data.parse_data({"facts": items}).facts
                outcomes.append(("ok", [(f.name, str(f.number), f.unit, str(f.derived)) for f in facts]))
            except Exception as exc:
                outcomes.append(("error", type(exc).__name__, str(exc)))
        if outcomes[0] != outcomes[1]:
            differences.append(f"parse_data {items}\n    ref: {outcomes[0]}\n    now: {outcomes[1]}")
    return differences


def load_ref(ref: str, into: Path) -> ModuleType:
    """The package as it was at `ref`, imported under another name beside this checkout's."""
    try:
        archive = subprocess.run(["git", "archive", "--format=tar", ref, PACKAGE], cwd=ROOT, capture_output=True)
    except FileNotFoundError:
        raise SystemExit("cannot read the ref: git is not installed") from None
    if archive.returncode != 0:
        raise SystemExit(f"cannot read {PACKAGE}/ at {ref}: {archive.stderr.decode(errors='replace').strip()}")
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        members = []
        for member in tar.getmembers():
            if member.name == PACKAGE or member.name.startswith(PACKAGE + "/"):
                member.name = REF_PACKAGE + member.name[len(PACKAGE) :]
                members.append(member)
        tar.extractall(into, members=members, filter="data")
    # Renamed, the package only works if it imports itself relatively.
    for module in (into / REF_PACKAGE).rglob("*.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            absolute = [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                absolute = [node.module]
            if any(name == PACKAGE or name.startswith(PACKAGE + ".") for name in absolute):
                raise SystemExit(f"{module.name} at {ref} imports {PACKAGE} by name: it cannot be compared this way")
    sys.path.insert(0, str(into))
    return importlib.import_module(REF_PACKAGE)


def load_checkout() -> ModuleType:
    """This checkout's package, not a copy pip installed in site-packages."""
    sys.path.insert(0, str(ROOT))
    package = importlib.import_module(PACKAGE)
    if not Path(str(package.__file__)).resolve().is_relative_to(ROOT):
        raise SystemExit(f"imported {package.__file__} instead of this checkout's {PACKAGE}")
    return package


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("ref", nargs="?", default="HEAD", help="the git ref to compare with (default: HEAD)")
    parser.add_argument("--documents", type=int, default=2000, help="random documents to compare (default 2000)")
    parser.add_argument("--data", type=int, default=5000, help="random lists of computed facts (default 5000)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--ignore", action="append", default=[], metavar="CHECK",
        help="leave out findings of this check, when a version changed them on purpose (repeatable)",
    )  # fmt: skip
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):  # a console that cannot show «￼» shows ￼
        sys.stdout.reconfigure(errors="backslashreplace")

    with tempfile.TemporaryDirectory() as folder:
        try:
            new = load_checkout()
            old = load_ref(args.ref, Path(folder))
        except SystemExit as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"{args.ref}: {old.__version__}, {old.RECIPE}\nthis checkout: {new.__version__}, {new.RECIPE}")
        rng = random.Random(args.seed)
        differences = compare_documents(old, new, rng, args.documents, frozenset(args.ignore))
        print(f"documents: {args.documents}, {len(differences)} with different decisions")
        if hasattr(old, "percent_change") and hasattr(new, "percent_change"):
            importlib.import_module(f"{REF_PACKAGE}.data")
            importlib.import_module(f"{PACKAGE}.data")
            found = compare_data(old, new, rng, args.data)
            print(f"computed facts: {args.data} lists, {len(found)} parsed differently")
            differences += found
    for difference in differences[:5]:
        print("\n" + difference)
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())
