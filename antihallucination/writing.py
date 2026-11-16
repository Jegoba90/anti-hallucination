"""write(): ask a model for the draft, then compose() it under your numbers.

The writer is any callable that takes (system, prompt) and returns text:
ClaudeWriter, OpenAICompatibleWriter (OpenAI, Groq, Ollama, LM Studio...), or
your own function. It is told the placeholders, never the figures. Whatever it
returns goes through compose(): figures from your facts, every sentence
checked, failures dropped or replaced by your fallbacks.

When a draft has failed sentences, the writer is asked again, with each
failure explained (without the values it was not shown), up to `retries`
times. The attempt with the fewest failed sentences goes out; on a tie, the
later one. Each attempt is kept, so you can see what the model tried.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from .checks import Policy
from .core import Result, compose
from .errors import WriterError
from .facts import Fact, Label, Source, check_computed
from .prompt import build_prompt, feedback

Writer = Callable[[str, str], str]
_NAME_RE = re.compile(r"[^\W\d_][\w'’.\-&]*")


@dataclass(frozen=True)
class Written:
    """What write() produced: the result that goes out, and every attempt behind it."""

    result: Result
    attempts: tuple[Result, ...]
    errors: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return self.result.text


def writer_name(writer: Writer) -> str:
    """How a writer is named in the receipt: its .name, its function name, or "writer"."""
    name: object = getattr(writer, "name", None) or getattr(writer, "__name__", None)
    served: object = getattr(writer, "served_by", "")
    text = name if isinstance(name, str) and name else "writer"
    if isinstance(served, str) and served and served not in text:
        text += f" (served by {served})"
    return text


def _names_in(brief: str) -> tuple[str, ...]:
    """Capitalized words of the brief: names you gave the writer yourself."""
    found: list[str] = []
    for match in _NAME_RE.finditer(brief):
        word = match.group(0).strip(".'’-&")
        if word and any(ch.isupper() for ch in word) and word not in found:
            found.append(word)
    return tuple(found)


def _failed(result: Result) -> int:
    return sum(1 for decision in result.decisions if decision.findings)


def write(
    brief: str,
    facts: Sequence[Fact] = (),
    labels: Sequence[Label] = (),
    sources: Sequence[Source] = (),
    *,
    writer: Writer,
    fallbacks: Mapping[str, str] | None = None,
    policy: Policy | None = None,
    locale: str = "en",
    retries: int = 1,
) -> Written:
    """Have `writer` draft a text for `brief`, and publish only what passes.

    Names in the brief count as given: «report for Acme» lets the text say
    Acme. Figures in the brief do not: the writer still has to use a
    placeholder. Raises WriterError if the first draft cannot be had; a writer
    failure on a retry keeps the attempts already made.
    """
    if retries < 0:
        raise ValueError("retries cannot be negative")
    # A computed fact that does not hold its value fails now, before a model is paid for.
    check_computed({fact.name: fact for fact in facts})
    base = policy or Policy()
    allowed = replace(base, known_names=tuple(dict.fromkeys([*base.known_names, *_names_in(brief)])))
    system, prompt = build_prompt(brief, list(facts), list(labels), list(sources), allowed, locale)

    attempts: list[Result] = []
    errors: list[str] = []
    asked = prompt
    for attempt in range(retries + 1):
        try:
            draft = writer(system, asked)
        except WriterError as exc:
            if not attempts:
                raise
            errors.append(str(exc))
            break
        if not isinstance(draft, str):
            raise WriterError("the writer did not return text")
        result = compose(
            draft, facts, labels, sources, fallbacks=fallbacks, policy=allowed, locale=locale, writer=writer_name(writer)
        )
        attempts.append(result)
        if result.ok or attempt == retries:
            break
        asked = feedback(prompt, draft, result)

    best = attempts[0]
    for result in attempts[1:]:
        if _failed(result) <= _failed(best):
            best = result
    return Written(result=best, attempts=tuple(attempts), errors=tuple(errors))
