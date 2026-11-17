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
from bisect import bisect_left
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache

from . import lexicon
from .facts import Fact, Label, Source, check_computed
from .numbers import Mention, backed_by_values, evidence_values, extract, match_fact
from .text import MASK, Clauses, fold, last_words, lower, mask

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z_]+))?\}")
CITATION_RE = re.compile(r"\[([A-Za-z0-9_.\-]+(?:\s*,\s*[A-Za-z0-9_.\-]+)*)\]")
MODIFIERS = frozenset({"abs", "signed"})
_WORD_RE = re.compile(r"[^\W\d_][\w'’.\-&]*")
_EDGE = ".,;:-'’\"«»“”()¿?¡!"
_OPENERS = ":¿¡«\"“(—–-"
_BEFORE_A_WORD = " " + MASK
_MOVES = (("up", lexicon.UP), ("down", lexicon.DOWN))


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


@lru_cache(maxsize=4096)
def _word_matchers(word: str) -> tuple[re.Pattern[str], ...]:
    """The patterns that find `word` (folded) as a whole word, plural or singular.

    A word ending in «es» or «s» is also looked for without it, and a word
    with dots also without them. Compiled once per word: a sentence is
    checked against every subject and every name, and compiling each time
    costs more than the search.
    """
    if not word:
        return ()
    candidates = [word]
    if word.endswith("es") and len(word) > 4:
        candidates.append(word[:-2])
    if word.endswith("s") and len(word) > 3:
        candidates.append(word[:-1])
    matchers = [
        re.compile(r"(?<![a-z0-9])" + re.escape(candidate) + r"(?:s|es)?(?![a-z0-9])")
        for candidate in dict.fromkeys(candidates)
    ]
    if "." in word:
        matchers.extend(_word_matchers(word.replace(".", "")))
    return tuple(matchers)


def _contains_word(haystack: str, matchers: tuple[re.Pattern[str], ...]) -> bool:
    """Whether `haystack` (folded) holds the word those matchers look for."""
    return any(matcher.search(haystack) for matcher in matchers)


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
        # Read once here instead of once per sentence or per word: which way
        # each source says something moved, what each fact's subject looks
        # like, how each verdict reads when quoted, and whether a verdict's own
        # words say the value fell («caída leve»).
        self.source_moves: dict[str, frozenset[str]] = {}
        for sid, source in self.sources.items():
            lowered = lower(source.evidence)
            self.source_moves[sid] = frozenset(polarity for polarity, pattern in _MOVES if pattern.search(lowered))
        self.subject_matchers = {
            name: tuple(matcher for word in fact.subjects for matcher in _word_matchers(fold(word)))
            for name, fact in self.facts.items()
        }
        self.label_quotes: list[tuple[str, str, re.Pattern[str]]] = []
        for name, label in self.labels.items():
            phrase = lower(label.text.strip())
            self.label_quotes.append((name, phrase, re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)")))
        self.label_minus = {
            name: _carries_minus(lower(label.text), (0, len(label.text))) for name, label in self.labels.items()
        }
        self._backed: dict[tuple[str, str, tuple[str, ...]], bool] = {}

    def evidence_for(self, cited: list[str]) -> list[str]:
        """The sources a sentence may draw on: the ones it cites, or all of them."""
        return cited if cited else list(self.sources)

    def _evidence(self, sources: tuple[str, ...]) -> list[str]:
        return [self.base_evidence, *(self.source_evidence[sid] for sid in sources)]

    def name_backed(self, core: str, sources: tuple[str, ...]) -> bool:
        """Whether a name (folded) is in your facts, labels, known names or these sources."""
        key = ("name", core, sources)
        if key not in self._backed:
            matchers = _word_matchers(core)
            self._backed[key] = any(_contains_word(text, matchers) for text in self._evidence(sources))
        return self._backed[key]

    def identifier_backed(self, raw: str, sources: tuple[str, ...]) -> bool:
        """Whether an identifier («Q3», «COVID-19») is written in your data or these sources."""
        key = ("identifier", raw, sources)
        if key not in self._backed:
            self._backed[key] = any(_identifier_backed(raw, text) for text in self._evidence(sources))
        return self._backed[key]


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
    words = last_words(text, clause_start, position, 3)
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


class _Subjects:
    """The facts whose subject a stretch of one sentence names, each stretch read once.

    Every move word in a clause asks about the same clause, and every one
    with no subject asks about the whole sentence: reading it again for each
    word would make a long sentence cost its length times its words.
    """

    def __init__(self, masked: str, ctx: Context) -> None:
        self._masked = masked
        self._ctx = ctx
        self._found: dict[tuple[int, int], list[str]] = {}

    def named(self, span: tuple[int, int]) -> list[str]:
        """The facts (in your order) whose subject masked[start:end] names."""
        if span not in self._found:
            folded = fold(self._masked[span[0] : span[1]])
            self._found[span] = [
                name for name, matchers in self._ctx.subject_matchers.items() if _contains_word(folded, matchers)
            ]
        return self._found[span]


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
        initial = _opens_sentence(text, match.start())
        letters = [ch for ch in token if ch.isalpha()]
        acronym = len(letters) >= 2 and all(ch.isupper() for ch in letters)
        camel = any(ch.isupper() for ch in token[1:]) and not acronym
        if initial and not (acronym or camel):
            continue
        candidates.append(token.strip(_EDGE))
    return candidates


def _opens_sentence(text: str, start: int) -> bool:
    """Whether the word at `start` comes first: after nothing, «:», «¿», «(»..., spaces and placeholders aside.

    Read back from the word, not from the start of the sentence, so a long
    sentence full of capitals is read once.
    """
    index = start
    while index > 0 and text[index - 1] in _BEFORE_A_WORD:
        index -= 1
    return index == 0 or text[index - 1] in _OPENERS


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
        return ctx.identifier_backed(mention.raw, tuple(sources))
    if use_labels and backed_by_values(mention, ctx.label_values):
        return True
    return any(backed_by_values(mention, ctx.source_values[sid]) for sid in sources)


def _nearest(refs: list[_Reference], starts: list[int], clause: tuple[int, int], position: int) -> _Reference | None:
    """The reference inside the clause closest to `position`; on a tie, the one written first.

    refs are in the order of the text and `starts` holds where each one
    starts, so the clause and the closest reference are binary searches.
    """
    low = bisect_left(starts, clause[0])
    high = bisect_left(starts, clause[1])
    if low == high:
        return None
    after = bisect_left(starts, position, low, high)  # the first that starts at or after `position`
    if after == high or (after > low and position - starts[after - 1] <= starts[after] - position):
        # The closest one starts before `position`: the first written at that start.
        return refs[bisect_left(starts, starts[after - 1], low, high)]
    return refs[after]


def _any_within(starts: list[int], clause: tuple[int, int]) -> bool:
    """Whether a position in `starts` (in order) falls inside the clause."""
    index = bisect_left(starts, clause[0])
    return index < len(starts) and starts[index] < clause[1]


def _check_directions(
    masked: str,
    lowered: str,
    clauses: Clauses,
    subject_facts: _Subjects,
    ctx: Context,
    check: SentenceCheck,
    refs: list[_Reference],
) -> None:
    changes = sorted((ref for ref in refs if ctx.facts[ref.fact].change), key=lambda ref: ref.start)
    starts = [ref.start for ref in changes]
    # What a move with no figure of its own is judged against, per clause:
    # the changes it names (and whether they all point one way).
    judged: dict[tuple[int, int], tuple[list[Fact], bool]] = {}
    for polarity, pattern in _MOVES:
        for match in pattern.finditer(lowered):
            clause = clauses.of(match.start())
            negated = _negated(lowered, clause[0], match.start())
            word = masked[match.start() : match.end()]
            nearest = _nearest(changes, starts, clause, match.start())
            if nearest is not None:
                check.anchors += 1
                fact = ctx.facts[nearest.fact]
                if not _agrees(polarity, negated, fact.number):
                    check.findings.append(_contradiction(word, polarity, negated, fact, ctx))
                continue
            if clause not in judged:
                # Which change the word talks about: one whose subject the
                # clause names; if the clause names a subject with no change
                # («el ticket subió»), nothing backs the move; if it names
                # none, the sentence's.
                named = subject_facts.named(clause)
                if not named:
                    named = subject_facts.named((0, len(masked)))
                facts = [ctx.facts[name] for name in named if ctx.facts[name].change]
                # Two changes of that subject pointing different ways get no verdict.
                one_way = len({(fact.number > 0) - (fact.number < 0) for fact in facts}) == 1
                judged[clause] = (facts, one_way)
            facts, one_way = judged[clause]
            if facts:
                check.anchors += 1
                if one_way and not _agrees(polarity, negated, facts[0].number):
                    check.findings.append(_contradiction(word, polarity, negated, facts[0], ctx))
                continue
            if any(polarity in ctx.source_moves[sid] for sid in ctx.evidence_for(check.cited)):
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
        for name, phrase, quote in ctx.label_quotes:
            if phrase not in lowered_sentence:
                continue
            quoted = False
            for match in quote.finditer(lowered_sentence):
                hidden.append(match.span())
                verdicts.append((match.start(), name))
                check.anchors += 1
                quoted = True
            if quoted:
                check.labels.append(name)

    masked = mask(sentence, hidden)
    if ctx.policy.numbers:
        _check_figures(masked, ctx, check, refs, compose=compose)

    lowered = lower(masked)
    clauses = Clauses(masked)
    # Your verdict can carry the minus: «una {tendencia} de {variacion:abs}»
    # reads «una caída leve de 3,2 %», with no second word for the fall.
    minus_verdicts = sorted(start for start, name in verdicts if ctx.label_minus[name])
    says_it_fell: dict[tuple[int, int], bool] = {}
    for ref in refs:
        fact = ctx.facts[ref.fact]
        if ref.how != "abs" or fact.number >= 0:
            continue
        clause = clauses.of(ref.start)
        if clause not in says_it_fell:
            says_it_fell[clause] = _carries_minus(lowered, clause) or _any_within(minus_verdicts, clause)
        if not says_it_fell[clause]:
            check.findings.append(
                Finding(
                    "sign_dropped",
                    ref.span,
                    f"{fact.name} is {_shown(fact, ctx)}, written without its minus sign and no word says it fell",
                )
            )

    subject_facts = _Subjects(masked, ctx)
    if ctx.policy.directions:
        _check_directions(masked, lowered, clauses, subject_facts, ctx, check, refs)

    if ctx.policy.names:
        sources = tuple(ctx.evidence_for(check.cited))
        for name in _name_candidates(masked):
            core = fold(name).strip(_EDGE)
            if not core or core in lexicon.NOT_NAMES:
                continue
            if not ctx.name_backed(core, sources):
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

    listed = set(check.facts)  # a set beside the list: a figure can match many facts
    for ref in refs:
        if ref.fact not in listed:
            listed.add(ref.fact)
            check.facts.append(ref.fact)
    subjects: list[str] = []
    for name in [*check.facts, *subject_facts.named((0, len(masked)))]:
        for word in ctx.facts[name].subjects:
            if word not in subjects:
                subjects.append(word)
    check.subjects = subjects
    check.output = render_template(sentence, ctx) if compose else sentence
    return check
