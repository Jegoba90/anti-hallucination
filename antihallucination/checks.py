"""The checks one sentence goes through, and what each one found.

A sentence passes only if every check passes; one finding is enough to keep it
out. The checks, in the order they run:

1. Figures. In compose mode the writer may not type a figure at all: it writes
   {placeholders} and Python writes the numbers. A sentence that cites a source
   may copy a figure from that source. In verify mode every figure must be a
   fact rounded to the precision written, a figure inside a label, or a figure
   in the sources the sentence may use.
2. Signs. A negative value written without its minus sign needs a word that
   says it fell («cayeron 3,2 %»).
3. Directions. A word that says something went up or down must agree with the
   sign of the change it talks about, and a move nothing backs is a claim.
4. Names. A proper name must be in your facts, labels, sources or known names.
5. Claims. A forecast, a claim of certainty or a cause is a claim the numbers
   do not make (lexicon.py says how far those lists go).
6. Anchoring. A sentence that passed everything else must still carry
   something from your data, or cite a source. It needs no word list: a
   sentence with no data is the writer's opinion, however it is phrased.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import lexicon
from .facts import Fact, Label, Source, check_computed
from .numbers import Mention, backed_by_values, evidence_values, extract, match_fact
from .text import MASK, clause_of, fold, lower, mask, words_before

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z_]+))?\}")
CITATION_RE = re.compile(r"\[([A-Za-z0-9_.\-]+(?:\s*,\s*[A-Za-z0-9_.\-]+)*)\]")
MODIFIERS = frozenset({"abs", "signed"})
_WORD_RE = re.compile(r"[^\W\d_][\w'’.\-&]*")
_EDGE = ".,;:-'’\"«»“”()¿?¡!"
_OPENERS = ":¿¡«\"“(—–-"


@dataclass(frozen=True)
class Policy:
    """Which checks run, and the names you allow anywhere.

    Every check is on by default. known_names holds names no source has to
    carry: your company, your products, the people who sign the report.
    """

    numbers: bool = True
    names: bool = True
    directions: bool = True
    forecasts: bool = True
    certainty: bool = True
    causes: bool = True
    # Every sentence must carry something from your data (a figure, a verdict,
    # a direction checked against a change) or cite a source. Not a word list:
    # a sentence with no data is cut however it is phrased.
    anchored: bool = True
    known_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        names = (self.known_names,) if isinstance(self.known_names, str) else tuple(self.known_names)
        if not all(isinstance(name, str) and name.strip() for name in names):
            raise ValueError("known_names must be non-empty text")
        object.__setattr__(self, "known_names", tuple(name.strip() for name in names))

    def to_dict(self) -> dict[str, object]:
        return {
            "numbers": self.numbers,
            "names": self.names,
            "directions": self.directions,
            "forecasts": self.forecasts,
            "certainty": self.certainty,
            "causes": self.causes,
            "anchored": self.anchored,
            "known_names": list(self.known_names),
        }


@dataclass(frozen=True)
class Finding:
    """One reason a sentence did not go out.

    check is a stable code (unbacked_number, typed_number, unknown_placeholder,
    sign_dropped, direction_contradiction, unbacked_direction, unbacked_name,
    forecast, certainty, cause, unanchored); span is the text as written;
    detail says why.
    """

    check: str
    span: str
    detail: str


@dataclass(frozen=True)
class _Reference:
    fact: str
    start: int
    span: str  # the figure or placeholder as written
    how: str  # "exact" or "abs": whether the figure carries the fact's sign


@dataclass
class SentenceCheck:
    findings: list[Finding] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    cited: list[str] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    output: str = ""
    anchors: int = 0  # pieces of your data the sentence carries, for the anchoring check


def _contains_word(haystack: str, word: str) -> bool:
    """`word` (folded) in `haystack` (folded) as a whole word, plural or singular."""
    if not word:
        return False
    candidates = {word}
    if word.endswith("es") and len(word) > 4:
        candidates.add(word[:-2])
    if word.endswith("s") and len(word) > 3:
        candidates.add(word[:-1])
    for candidate in candidates:
        if re.search(r"(?<![a-z0-9])" + re.escape(candidate) + r"(?:s|es)?(?![a-z0-9])", haystack):
            return True
    if "." in word:
        return _contains_word(haystack, word.replace(".", ""))
    return False


class Context:
    """Your facts, labels, sources and policy, read once for every sentence."""

    def __init__(
        self,
        facts: list[Fact],
        labels: list[Label],
        sources: list[Source],
        policy: Policy,
        locale: str,
    ) -> None:
        self.facts: dict[str, Fact] = {}
        self.labels: dict[str, Label] = {}
        for fact in facts:
            if not isinstance(fact, Fact):
                raise TypeError("facts must be Fact objects")
            if fact.name in self.facts:
                raise ValueError(f"two facts are named {fact.name!r}")
            self.facts[fact.name] = fact
        check_computed(self.facts)
        for label in labels:
            if not isinstance(label, Label):
                raise TypeError("labels must be Label objects")
            if label.name in self.facts or label.name in self.labels:
                raise ValueError(f"a fact or label is already named {label.name!r}")
            self.labels[label.name] = label
        self.sources: dict[str, Source] = {}
        for source in sources:
            if source.id in self.sources:
                raise ValueError(f"two sources have the id {source.id!r}")
            self.sources[source.id] = source
        self.policy = policy
        self.locale = locale

        base = [*policy.known_names, *(label.text for label in labels)]
        for fact in facts:
            base.extend([fact.name.replace("_", " "), fact.label, fact.unit, *fact.subjects])
        self.base_evidence = fold("\n".join(base))
        # Evidence is read both ways: a source may be in another language than the text.
        self.label_values = evidence_values("\n".join(label.text for label in labels))
        self.source_evidence = {sid: fold(source.evidence) for sid, source in self.sources.items()}
        self.source_values = {sid: evidence_values(source.evidence) for sid, source in self.sources.items()}
        self.source_lower = {sid: lower(source.evidence) for sid, source in self.sources.items()}

    def evidence_for(self, cited: list[str]) -> list[str]:
        """The sources a sentence may draw on: the ones it cites, or all of them."""
        return cited if cited else list(self.sources)


def _shown(fact: Fact, ctx: Context) -> str:
    """A fact as Python writes it, for a finding a person will read."""
    return fact.render(ctx.locale if ctx.locale in ("es", "en") else "en")


def _render_placeholder(match: re.Match[str], ctx: Context) -> str:
    name, modifier = match.group(1), match.group(2) or ""
    if name in ctx.facts:
        return ctx.facts[name].render(ctx.locale, modifier)
    if name in ctx.labels:
        return ctx.labels[name].text
    return match.group(0)


def render_template(template: str, ctx: Context) -> str:
    """A text Python writes, with every placeholder filled. Not checked: it is yours."""
    return PLACEHOLDER_RE.sub(lambda match: _render_placeholder(match, ctx), template)


def template_problems(template: str, ctx: Context) -> list[str]:
    """What is wrong with the placeholders of a template you wrote."""
    problems: list[str] = []
    for match in PLACEHOLDER_RE.finditer(template):
        name, modifier = match.group(1), match.group(2)
        if name not in ctx.facts and name not in ctx.labels:
            problems.append(f"{{{name}}} names no fact or label")
        elif modifier and (name in ctx.labels or modifier not in MODIFIERS):
            problems.append(f"{match.group(0)} has a modifier it cannot take")
    return problems


def _identifier_backed(raw: str, evidence: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(fold(raw)) + r"(?![\w-])", evidence) is not None


def _negated(text: str, clause_start: int, position: int) -> bool:
    """Whether a negator in the three words before `position` (same clause) turns the word around."""
    words = words_before(text[clause_start:position], position - clause_start, 3)
    for index, word in enumerate(words):
        if word in lexicon.NEGATORS:
            following = words[index + 1] if index + 1 < len(words) else ""
            if following not in lexicon.NOT_A_NEGATION:
                return True
    return False


def _agrees(polarity: str, negated: bool, value: Decimal) -> bool:
    if polarity == "up":
        return value <= 0 if negated else value > 0
    return value >= 0 if negated else value < 0


def _subject_facts(window: str, ctx: Context, *, change_only: bool) -> list[str]:
    folded = fold(window)
    found: list[str] = []
    for fact in ctx.facts.values():
        if change_only and not fact.change:
            continue
        if any(_contains_word(folded, fold(word)) for word in fact.subjects):
            found.append(fact.name)
    return found


def _carries_minus(lowered: str, clause: tuple[int, int]) -> bool:
    """Whether a word in the clause says the value is down or negative."""
    start, end = clause
    segment = lowered[start:end]
    for match in lexicon.DOWN.finditer(segment):
        if not _negated(lowered, start, start + match.start()):
            return True
    return lexicon.NEGATIVE_NOUNS.search(segment) is not None


def _name_candidates(text: str) -> list[str]:
    """Capitalized words that are not just the first word of a sentence."""
    candidates: list[str] = []
    for match in _WORD_RE.finditer(text):
        token = match.group(0).rstrip(".")
        if any(ch.isdigit() for ch in token) or not any(ch.isupper() for ch in token):
            continue
        before = text[: match.start()].rstrip(" " + MASK)
        initial = not before or before[-1] in _OPENERS
        letters = [ch for ch in token if ch.isalpha()]
        acronym = len(letters) >= 2 and all(ch.isupper() for ch in letters)
        camel = any(ch.isupper() for ch in token[1:]) and not acronym
        if initial and not (acronym or camel):
            continue
        candidates.append(token.strip(_EDGE))
    return candidates


def _stray_numerals(masked: str, mentions: list[Mention]) -> list[str]:
    """Numeral characters no figure accounts for: «²», «½», «Ⅲ», a digit after «_».

    compose() promises that the writer typed no digit, so anything numeric the
    figure reader did not see still counts as typed.
    """
    covered = [False] * len(masked)
    for mention in mentions:
        for index in range(mention.start, mention.end):
            covered[index] = True
    runs: list[str] = []
    run = ""
    for index, ch in enumerate(masked):
        if ch.isnumeric() and not covered[index]:
            run += ch
        elif run:
            runs.append(run)
            run = ""
    if run:
        runs.append(run)
    return runs


def _check_figures(masked: str, ctx: Context, check: SentenceCheck, refs: list[_Reference], *, compose: bool) -> None:
    sources = ctx.evidence_for(check.cited)
    mentions = extract(masked, ctx.locale)
    if compose:
        for run in _stray_numerals(masked, mentions):
            check.findings.append(
                Finding("typed_number", run, f"«{run}» was typed by the writer; figures come from placeholders")
            )
    for mention in mentions:
        if compose and not check.cited:
            check.findings.append(
                Finding("typed_number", mention.raw, f"«{mention.raw}» was typed by the writer; figures come from placeholders")
            )
            continue
        if not compose and not mention.identifier:
            matched = _match_facts(mention, ctx)
            if matched is not None:
                how, names = matched
                if how == "sign":
                    fact = ctx.facts[names[0]]
                    check.findings.append(
                        Finding(
                            "direction_contradiction",
                            mention.raw,
                            f"«{mention.raw}» has the opposite sign of {fact.name} ({_shown(fact, ctx)})",
                        )
                    )
                else:
                    refs.extend(_Reference(name, mention.start, mention.raw, how) for name in names)
                continue
        if _backed_elsewhere(mention, ctx, sources, use_labels=not compose):
            check.anchors += 1
            continue
        where = "the cited source" if check.cited else "your facts, labels or sources"
        check.findings.append(Finding("unbacked_number", mention.raw, f"«{mention.raw}» is not in {where}"))


def _match_facts(mention: Mention, ctx: Context) -> tuple[str, list[str]] | None:
    """The facts a figure stands for: exact matches first, then sign-dropped, then opposite sign."""
    by_kind: dict[str, list[str]] = {"exact": [], "abs": [], "sign": []}
    for fact in ctx.facts.values():
        how = match_fact(mention, fact.number, fact.is_percent)
        if how is not None:
            by_kind[how].append(fact.name)
    for kind in ("exact", "abs", "sign"):
        if by_kind[kind]:
            return kind, by_kind[kind]
    return None


def _backed_elsewhere(mention: Mention, ctx: Context, sources: list[str], *, use_labels: bool) -> bool:
    if mention.identifier:
        evidence = [ctx.base_evidence, *(ctx.source_evidence[sid] for sid in sources)]
        return any(_identifier_backed(mention.raw, text) for text in evidence)
    if use_labels and backed_by_values(mention, ctx.label_values):
        return True
    return any(backed_by_values(mention, ctx.source_values[sid]) for sid in sources)


def _check_directions(masked: str, ctx: Context, check: SentenceCheck, refs: list[_Reference]) -> None:
    lowered = lower(masked)
    for polarity, pattern in (("up", lexicon.UP), ("down", lexicon.DOWN)):
        for match in pattern.finditer(lowered):
            clause = clause_of(masked, match.start())
            negated = _negated(lowered, clause[0], match.start())
            word = masked[match.start() : match.end()]
            near = [r for r in refs if clause[0] <= r.start < clause[1] and ctx.facts[r.fact].change]
            if near:
                check.anchors += 1
                fact = ctx.facts[min(near, key=lambda r: abs(r.start - match.start())).fact]
                if not _agrees(polarity, negated, fact.number):
                    check.findings.append(_contradiction(word, polarity, negated, fact, ctx))
                continue
            # Which change the word talks about: one whose subject the clause
            # names; if the clause names a subject with no change («el ticket
            # subió»), nothing backs the move; if it names none, the sentence's.
            clause_text = masked[clause[0] : clause[1]]
            facts = [ctx.facts[name] for name in _subject_facts(clause_text, ctx, change_only=True)]
            if not facts and not _subject_facts(clause_text, ctx, change_only=False):
                facts = [ctx.facts[name] for name in _subject_facts(masked, ctx, change_only=True)]
            if facts:
                check.anchors += 1
                # Two changes of that subject pointing different ways get no verdict.
                directions = {(fact.number > 0) - (fact.number < 0) for fact in facts}
                if len(directions) == 1 and not _agrees(polarity, negated, facts[0].number):
                    check.findings.append(_contradiction(word, polarity, negated, facts[0], ctx))
                continue
            if any(pattern.search(ctx.source_lower[sid]) for sid in ctx.evidence_for(check.cited)):
                continue
            check.findings.append(
                Finding("unbacked_direction", word, f"«{word}» claims a move that no change fact or source backs")
            )


def _anchored(check: SentenceCheck, refs: list[_Reference]) -> bool:
    """Whether the sentence carries something from your data, or cites a source.

    Your data is a fact (a placeholder, or a figure that matches one), a label
    (its placeholder, or its words as you wrote them), a figure a label or a
    source backs, or a move checked against a change. «El desempeño se
    mantiene dentro de lo esperado» carries none of them: it is the writer's
    opinion, and it is cut whatever its words are.
    """
    return bool(refs or check.labels or check.cited or check.anchors)


def _contradiction(word: str, polarity: str, negated: bool, fact: Fact, ctx: Context) -> Finding:
    said = ("not " if negated else "") + ("up" if polarity == "up" else "down")
    return Finding("direction_contradiction", word, f"«{word}» says {said}, but {fact.name} is {_shown(fact, ctx)}")


def check_sentence(sentence: str, ctx: Context, *, compose: bool) -> SentenceCheck:
    """Run every check on one sentence and render what would go out."""
    check = SentenceCheck()
    hidden: list[tuple[int, int]] = []

    for match in CITATION_RE.finditer(sentence):
        ids = [part.strip() for part in match.group(1).split(",")]
        if all(sid in ctx.sources for sid in ids):
            check.cited.extend(sid for sid in ids if sid not in check.cited)
            hidden.append(match.span())

    refs: list[_Reference] = []
    verdicts: list[tuple[int, str]] = []  # where each of your labels sits: (start, label name)
    if compose:
        for match in PLACEHOLDER_RE.finditer(sentence):
            hidden.append(match.span())
            name, modifier = match.group(1), match.group(2)
            if name in ctx.facts and (modifier is None or modifier in MODIFIERS):
                refs.append(_Reference(name, match.start(), match.group(0), "abs" if modifier == "abs" else "exact"))
            elif name in ctx.labels and modifier is None:
                verdicts.append((match.start(), name))
                if name not in check.labels:
                    check.labels.append(name)
            else:
                check.findings.append(
                    Finding("unknown_placeholder", match.group(0), f"{match.group(0)} names no fact or label it can fill")
                )
    else:
        # A verified text may quote your verdicts as you wrote them («una caída
        # leve»). Those words are yours, as a {label} is in compose: they carry
        # data and are not checked again as the writer's (the «caída» in them
        # is not a move the writer claimed).
        lowered_sentence = lower(sentence)
        for label in ctx.labels.values():
            phrase = lower(label.text.strip())
            for match in re.finditer(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", lowered_sentence):
                hidden.append(match.span())
                verdicts.append((match.start(), label.name))
                check.anchors += 1
                if label.name not in check.labels:
                    check.labels.append(label.name)

    masked = mask(sentence, hidden)
    if ctx.policy.numbers:
        _check_figures(masked, ctx, check, refs, compose=compose)

    lowered = lower(masked)
    for ref in refs:
        fact = ctx.facts[ref.fact]
        clause = clause_of(masked, ref.start)
        # Your verdict can carry the minus: «una {tendencia} de {variacion:abs}»
        # reads «una caída leve de 3,2 %», with no second word for the fall.
        verdict_says_it = any(
            clause[0] <= start < clause[1] and _carries_minus(lower(ctx.labels[name].text), (0, len(ctx.labels[name].text)))
            for start, name in verdicts
        )
        if ref.how == "abs" and fact.number < 0 and not (_carries_minus(lowered, clause) or verdict_says_it):
            check.findings.append(
                Finding(
                    "sign_dropped",
                    ref.span,
                    f"{fact.name} is {_shown(fact, ctx)}, written without its minus sign and no word says it fell",
                )
            )

    if ctx.policy.directions:
        _check_directions(masked, ctx, check, refs)

    if ctx.policy.names:
        evidence = [ctx.base_evidence, *(ctx.source_evidence[sid] for sid in ctx.evidence_for(check.cited))]
        for name in _name_candidates(masked):
            core = fold(name).strip(_EDGE)
            if not core or core in lexicon.NOT_NAMES:
                continue
            if not any(_contains_word(text, core) for text in evidence):
                check.findings.append(
                    Finding("unbacked_name", name, f"«{name}» is not in your facts, labels, sources or known names")
                )

    for enabled, code, pattern, why in (
        (ctx.policy.forecasts, "forecast", lexicon.FORECAST, "forecasts; the text may only describe the data"),
        (ctx.policy.certainty, "certainty", lexicon.CERTAINTY, "claims a certainty the numbers do not carry"),
        (ctx.policy.causes, "cause", lexicon.CAUSE, "states a cause your data does not record"),
    ):
        if enabled:
            for match in pattern.finditer(lowered):
                span = masked[match.start() : match.end()]
                check.findings.append(Finding(code, span, f"«{span}» {why}"))

    # Anchoring: only reported for a sentence nothing else failed, where it is
    # the one reason; a sentence already out for a typed figure needs no second.
    if ctx.policy.anchored and not check.findings and not _anchored(check, refs):
        check.findings.append(
            Finding("unanchored", sentence, "it carries none of your facts or labels and cites no source")
        )

    for ref in refs:
        if ref.fact not in check.facts:
            check.facts.append(ref.fact)
    subjects: list[str] = []
    for name in [*check.facts, *_subject_facts(masked, ctx, change_only=False)]:
        for word in ctx.facts[name].subjects:
            if word not in subjects:
                subjects.append(word)
    check.subjects = subjects
    check.output = render_template(sentence, ctx) if compose else sentence
    return check
