"""Text as the checks read it: lines, sentences, clauses and folded forms.

Every check works on one sentence at a time, because a sentence is what gets
kept, dropped or replaced. Positions matter (a direction word belongs to the
number nearest to it), so nothing here rewrites the text it splits: masking
swaps a span for filler of the same length, and the offsets stay valid.

Nothing here reads the text again for every word: a sentence of any length,
with or without punctuation, costs about as much as reading it once.
"""

import re
import unicodedata
from bisect import bisect_right

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
# A run of these marks ends a sentence when whitespace follows. The run is read
# from its first mark and never given back: a line of ten thousand dots with no
# space after them is read once, not once for every dot.
_BOUNDARY = re.compile(r"(?<![.!?…])[.!?…]++[\"'»”’)\]]*+(?=\s)")
_CITATION_ONLY = re.compile(r"^(?:\[[^\[\]]+\]\s*)+$")


def _last_word(line: str, start: int, end: int) -> str:
    """The last word of line[start:end] as str.split() cuts it, read from the end."""
    stop = end
    while stop > start and line[stop - 1].isspace():
        stop -= 1
    begin = stop
    while begin > start and not line[begin - 1].isspace():
        begin -= 1
    return line[begin:stop]


def _next_char(line: str, start: int) -> str:
    """The first character from `start` on that is not whitespace, or ""."""
    for index in range(start, len(line)):
        if not line[index].isspace():
            return line[index]
    return ""


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
        last_word = fold(_last_word(line, start, match.start())).strip("(«\"'")
        initial = len(last_word) == 1 and last_word.isalpha()
        if last_word in _ABBREVIATIONS or initial or _next_char(line, match.end()).islower():
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


class Clauses:
    """The clauses of one sentence, found once and looked up for every position."""

    def __init__(self, sentence: str) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []
        for match in _CLAUSE_BREAK.finditer(sentence):
            self._starts.append(match.start())
            self._ends.append(match.end())
        self._length = len(sentence)

    def of(self, position: int) -> tuple[int, int]:
        """The (start, end) of the clause that holds `position`.

        It runs from the end of the last break that ends at or before
        `position` to the start of the first break that starts after it, so
        a position inside a break gets both clauses around that break.
        """
        before = bisect_right(self._ends, position)
        after = bisect_right(self._starts, position)
        start = self._ends[before - 1] if before else 0
        end = self._starts[after] if after < len(self._starts) else self._length
        return start, end


_WORD = re.compile(r"[\w'’]+")


def last_words(text: str, start: int, end: int, count: int) -> list[str]:
    """The last `count` words of text[start:end], casefolded.

    It reads back only as far as those words reach, so asking at every word of
    a long sentence costs about as much as reading the sentence once.
    """
    reach = 64
    while True:
        low = max(start, end - reach)
        words = _WORD.findall(text[low:end])
        # The window may cut the first word it finds; with more than `count`
        # words found, that one is not among the last `count`.
        if low == start or len(words) > count:
            return [word.casefold() for word in words[-count:]]
        reach *= 4


def lower(text: str) -> str:
    """`text` in lowercase without changing its length, so offsets stay valid.

    str.lower() turns «İ» into two characters; such a character is kept as is.
    """
    return "".join(low if len(low := ch.lower()) == 1 else ch for ch in text)
