"""compose() and verify(): the two ways to put a writer under your numbers.

compose() is for text you are about to publish. The writer (any LLM, or a
person) writes with placeholders, {ventas}, and never types a figure. Python
fills every placeholder from your facts and labels, checks each sentence, and
publishes only the ones that pass. A sentence that fails is dropped, or
replaced by a sentence you wrote yourself (a fallback), never repaired.

verify() is for text someone already wrote, with figures typed in: a model's
answer, a report, a summary. Every figure must be one of your facts rounded to
the precision written, or a figure your labels or sources contain.

Both return the final text, a decision per sentence and a receipt.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum

from .checks import (
    PLACEHOLDER_RE,
    Context,
    Finding,
    Policy,
    check_sentence,
    render_template,
    template_problems,
)
from .facts import Derivation, Fact, Label, Source, check_computed
from .numbers import LOCALES
from .receipt import (
    RECIPE,
    Receipt,
    ReceiptStatus,
    fact_record,
    label_record,
    load,
    source_record,
    verify_receipt,
)
from .text import fold, split_lines, split_sentences


@dataclass(frozen=True)
class Decision:
    """What happened to one sentence.

    action is "kept", "dropped" or "replaced". output is what went out in its
    place: the sentence with its figures written ("kept"), your fallback
    ("replaced"), or nothing ("dropped").
    """

    index: int
    input: str
    output: str
    action: str
    findings: tuple[Finding, ...]
    facts: tuple[str, ...]
    labels: tuple[str, ...]
    sources: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "input": self.input,
            "output": self.output,
            "action": self.action,
            "findings": [
                {"check": finding.check, "span": finding.span, "detail": finding.detail} for finding in self.findings
            ],
            "facts": list(self.facts),
            "labels": list(self.labels),
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class Result:
    text: str
    decisions: tuple[Decision, ...]
    receipt: Receipt

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(finding for decision in self.decisions for finding in decision.findings)

    @property
    def ok(self) -> bool:
        """True when every sentence passed as written."""
        return not self.findings


def compose(
    draft: str,
    facts: Sequence[Fact] = (),
    labels: Sequence[Label] = (),
    sources: Sequence[Source] = (),
    *,
    fallbacks: Mapping[str, str] | None = None,
    policy: Policy | None = None,
    locale: str = "en",
    writer: str = "",
) -> Result:
    """Fill a writer's draft from your facts and publish only what passes.

    draft: the writer's text, with {fact} / {fact:abs} / {fact:signed} and
        {label} placeholders, and [source_id] citations.
    fallbacks: subject → a sentence you write with placeholders. When a
        sentence about that subject fails, yours goes out in its place.
    locale: "es" or "en", how Python writes the figures.
    writer: who wrote the draft ("anthropic:claude-opus-5-5"), for the receipt.
    """
    if locale not in ("es", "en"):
        raise ValueError('compose writes figures in "es" or "en"')
    return _run("compose", draft, facts, labels, sources, fallbacks, policy or Policy(), locale, writer)


def verify(
    text: str,
    facts: Sequence[Fact] = (),
    labels: Sequence[Label] = (),
    sources: Sequence[Source] = (),
    *,
    fallbacks: Mapping[str, str] | None = None,
    policy: Policy | None = None,
    locale: str = "auto",
    writer: str = "",
) -> Result:
    """Check a finished text against your facts, labels and sources.

    locale: how to read «1.250»: "es" (a thousand two hundred and fifty), "en"
        (one and a quarter) or "auto" (either).
    writer: who wrote the text, if you know it, for the receipt.
    """
    if locale not in LOCALES:
        raise ValueError(f"locale must be one of {LOCALES}")
    return _run("verify", text, facts, labels, sources, fallbacks, policy or Policy(), locale, writer)


def _run(
    mode: str,
    text: str,
    facts: Sequence[Fact],
    labels: Sequence[Label],
    sources: Sequence[Source],
    fallbacks: Mapping[str, str] | None,
    policy: Policy,
    locale: str,
    writer: str,
) -> Result:
    if not isinstance(text, str):
        raise TypeError("the text must be a string")
    ctx = Context(list(facts), list(labels), list(sources), policy, locale)
    templates = dict(fallbacks or {})
    declared = {fold(word) for fact in ctx.facts.values() for word in fact.subjects}
    for subject, template in templates.items():
        if fold(subject) not in declared:
            raise ValueError(f"fallback {subject!r} is not the subject of any fact")
        problems = template_problems(template, ctx)
        if problems:
            raise ValueError(f"fallback {subject!r}: {'; '.join(problems)}")

    planned = [[(sentence, check_sentence(sentence, ctx, compose=mode == "compose")) for sentence in split_sentences(line)] for line in split_lines(text)]
    kept_facts = {name for line in planned for _, check in line if not check.findings for name in check.facts}

    used_templates: set[str] = set()
    used_sources: set[str] = set()
    decisions: list[Decision] = []
    out_lines: list[tuple[str, bool]] = []
    for line, sentences in zip(split_lines(text), planned):
        pieces: list[str] = []
        for sentence, check in sentences:
            if not check.findings:
                action, output = "kept", check.output
            else:
                inserted: list[str] = []
                subjects = {fold(word) for word in check.subjects}
                for subject, template in templates.items():
                    if subject in used_templates or fold(subject) not in subjects:
                        continue
                    needs = {match.group(1) for match in PLACEHOLDER_RE.finditer(template)} & set(ctx.facts)
                    if needs and needs <= kept_facts:
                        continue  # every figure it would give is already out
                    used_templates.add(subject)
                    inserted.append(render_template(template, ctx))
                for sid in check.cited:
                    fallback = ctx.sources[sid].fallback
                    if fallback and sid not in used_sources:
                        used_sources.add(sid)
                        inserted.append(fallback)
                action = "replaced" if inserted else "dropped"
                output = " ".join(inserted)
            if output:
                pieces.append(output)
            decisions.append(
                Decision(
                    index=len(decisions),
                    input=sentence,
                    output=output,
                    action=action,
                    findings=tuple(check.findings),
                    facts=tuple(check.facts),
                    labels=tuple(check.labels),
                    sources=tuple(check.cited),
                )
            )
        out_lines.append((" ".join(pieces), not line.strip()))

    final = _join(out_lines)
    body: dict[str, object] = {
        "recipe": RECIPE,
        "mode": mode,
        "locale": locale,
        "writer": writer,
        "input": text,
        "facts": [fact_record(fact) for fact in ctx.facts.values()],
        "labels": [label_record(label) for label in ctx.labels.values()],
        "sources": [source_record(source) for source in ctx.sources.values()],
        "fallbacks": templates,
        "policy": policy.to_dict(),
        "decisions": [decision.to_dict() for decision in decisions],
        "text": final,
    }
    return Result(text=final, decisions=tuple(decisions), receipt=Receipt.issue(body))


def _join(lines: list[tuple[str, bool]]) -> str:
    """Lines back together: emptied lines go, blank lines stay as single separators."""
    out: list[str] = []
    for content, was_blank in lines:
        if content:
            out.append(content)
        elif was_blank and out and out[-1] != "":
            out.append("")
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


class ReplayStatus(Enum):
    REPRODUCED = "reproduced"  # run again, the same inputs gave the same receipt
    DIFFERENT = "different"  # the inputs or the recipe now give another result
    INCOMPLETE = "incomplete"  # a source the receipt names was not provided
    UNREADABLE = "unreadable"  # the receipt cannot be read or does not match its digest


@dataclass(frozen=True)
class ReplayCheck:
    status: ReplayStatus
    reason: str = ""


def replay(receipt: Receipt | Mapping[str, object] | str, sources: Sequence[Source] = ()) -> ReplayCheck:
    """Run a receipt's decision again and check it arrives at the same digest.

    The receipt holds your facts, labels, policy and the writer's text; sources
    are recorded by hash only, so pass the same ones again.
    """
    check = verify_receipt(receipt)
    if check.status is not ReceiptStatus.VERIFIED:
        return ReplayCheck(ReplayStatus.UNREADABLE, check.reason)
    data = load(receipt)
    try:
        facts = [_fact(item) for item in _items(data, "facts")]
        labels = [Label(_text(item, "name"), _text(item, "text"), _text(item, "rule")) for item in _items(data, "labels")]
        policy_data = data.get("policy")
        if not isinstance(policy_data, dict):
            raise ValueError("policy is missing")
        policy = Policy(
            **{key: bool(policy_data.get(key)) for key in ("numbers", "names", "directions", "forecasts", "certainty", "causes", "anchored")},
            known_names=tuple(_strings(policy_data.get("known_names"))),
        )
        fallbacks_data = data.get("fallbacks")
        if not isinstance(fallbacks_data, dict):
            raise ValueError("fallbacks are missing")
        fallbacks = {str(key): str(value) for key, value in fallbacks_data.items()}
        mode, locale, text = _text(data, "mode"), _text(data, "locale"), _text(data, "input")
        writer = _text(data, "writer")
        recorded = {_text(item, "id"): _text(item, "sha256") for item in _items(data, "sources")}
    except (ValueError, TypeError, InvalidOperation) as exc:
        return ReplayCheck(ReplayStatus.UNREADABLE, f"the receipt cannot be rebuilt: {exc}")
    try:
        # A computed value edited after the fact, digest and all, is not what
        # its two facts give: computing it again is the replay.
        check_computed({fact.name: fact for fact in facts})
    except ValueError as exc:
        return ReplayCheck(ReplayStatus.DIFFERENT, str(exc))

    given = {source.id: source for source in sources}
    missing = [sid for sid in recorded if sid not in given]
    if missing:
        return ReplayCheck(ReplayStatus.INCOMPLETE, f"pass the sources it names: {', '.join(missing)}")
    for sid, sha in recorded.items():
        if source_record(given[sid])["sha256"] != sha:
            return ReplayCheck(ReplayStatus.DIFFERENT, f"source {sid} is not the one the receipt recorded")
    ordered = [given[sid] for sid in recorded]

    run = compose if mode == "compose" else verify
    again = run(text, facts, labels, ordered, fallbacks=fallbacks, policy=policy, locale=locale, writer=writer)
    if again.receipt.digest == data.get("digest"):
        return ReplayCheck(ReplayStatus.REPRODUCED)
    return ReplayCheck(ReplayStatus.DIFFERENT, "the same inputs now give another receipt")


def _items(data: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be a list of objects")
    return [{str(k): v for k, v in item.items()} for item in value]


def _text(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    return value


def _strings(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("expected a list of text values")
    return [str(item) for item in value]


def _fact(item: Mapping[str, object]) -> Fact:
    decimals = item.get("decimals")
    if decimals is not None and (isinstance(decimals, bool) or not isinstance(decimals, int)):
        raise ValueError("decimals must be an integer or null")
    how = item.get("derived")
    derived: Derivation | None = None
    if how is not None:
        if not isinstance(how, dict):
            raise ValueError("derived must be an object or null")
        derived = Derivation(_text(how, "compute"), _text(how, "from"), _text(how, "to"))
    return Fact(
        name=_text(item, "name"),
        value=Decimal(_text(item, "value")),
        unit=_text(item, "unit"),
        decimals=decimals,
        label=_text(item, "label"),
        subject=tuple(_strings(item.get("subject"))),
        change=item.get("change") is True,
        signed=item.get("signed") is True,
        compact=item.get("compact") is True,
        derived=derived,
    )
