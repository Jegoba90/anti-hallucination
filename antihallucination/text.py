"""Text as the checks read it: lines, sentences, clauses and folded forms.

Every check works on one sentence at a time, because a sentence is what gets
kept, dropped or replaced. Positions matter (a direction word belongs to the
number nearest to it), so nothing here rewrites the text it splits: masking
swaps a span for filler of the same length, and the offsets stay valid.
"""

import re
import unicodedata

# A run of this character hides a placeholder or a citation from the checks
# without moving anything: it is not a letter, digit, space or punctuation the
# patterns look for.
MASK = "￼"


def fold(text: str) -> str:
    """Casefolded and without accents, for comparing a text with its evidence."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def mask(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` with each span replaced by MASK characters of the same length."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            chars[index] = MASK
    return "".join(chars)


def split_lines(text: str) -> list[str]:
    """The lines of `text`; the newline style is not kept."""
    return re.split(r"\r\n|\n|\r", text)


# Words that end in a dot without ending a sentence. Folded, dot removed.
_ABBREVIATIONS = frozenset(
    {
        "sr", "sra", "srta", "dr", "dra", "lic", "ing", "prof", "mr", "mrs", "ms", "st", "vs", "etc",
        "inc", "ltd", "co", "corp", "nro", "num", "pag", "pp", "aprox", "approx", "ee", "uu",
        "e.g", "i.e", "fig", "jan", "feb", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov",
        "dec", "ene", "abr", "dic",
    }
)  # fmt: skip
_BOUNDARY = re.compile(r"[.!?…]+[\"'»”’)\]]*(?=\s)")
_CITATION_ONLY = re.compile(r"^(?:\[[^\[\]]+\]\s*)+$")


def split_sentences(line: str) -> list[str]:
    """The sentences of one line, stripped.

    A dot ends a sentence only when whitespace follows, so «3,2» and «1.250»
    never split, and not after a known abbreviation, a single letter («J.
    Smith») or before a lowercase word. A citation left alone after the dot
    («cayeron. [s1]») goes back to the sentence it cites.
    """
    sentences: list[str] = []
    start = 0
    for match in _BOUNDARY.finditer(line):
        before = line[start : match.start()].split()
        last_word = fold(before[-1]).strip("(«\"'") if before else ""
        rest = line[match.end() :].lstrip()
        initial = len(last_word) == 1 and last_word.isalpha()
        if last_word in _ABBREVIATIONS or initial or rest[:1].islower():
            continue
        sentence = line[start : match.end()].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()
    tail = line[start:].strip()
    if tail:
        sentences.append(tail)

    merged: list[str] = []
    for sentence in sentences:
        if merged and _CITATION_ONLY.match(sentence):
            merged[-1] = f"{merged[-1]} {sentence}"
        else:
            merged.append(sentence)
    return merged


# Where a clause ends: punctuation that is not inside a number («1,250»,
# «12:30»), a dash between spaces, and the conjunctions that join two claims.
_CLAUSE_BREAK = re.compile(
    r"(?<!\d)[,:](?!\d)|[;()—–]|\s-\s"
    r"|\b(?:y|pero|mientras|aunque|sino|and|but|while|whereas|although|though)\b",
    re.IGNORECASE,
)


def clause_of(sentence: str, position: int) -> tuple[int, int]:
    """The (start, end) of the clause that holds `position`."""
    start, end = 0, len(sentence)
    for match in _CLAUSE_BREAK.finditer(sentence):
        if match.end() <= position:
            start = match.end()
        elif match.start() > position:
            end = match.start()
            break
    return start, end


def words_before(text: str, position: int, count: int) -> list[str]:
    """The last `count` words before `position`, casefolded."""
    return [word.casefold() for word in re.findall(r"[\w'’]+", text[:position])][-count:]


def lower(text: str) -> str:
    """`text` in lowercase without changing its length, so offsets stay valid.

    str.lower() turns «İ» into two characters; such a character is kept as is.
    """
    return "".join(low if len(low := ch.lower()) == 1 else ch for ch in text)
