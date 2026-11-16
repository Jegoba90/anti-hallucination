"""The receipt: what went in, what each check decided, what went out.

The digest is a SHA-256 over the receipt's own content, serialized the same way
every time (sorted keys, compact separators, ASCII, numbers as decimal strings).
It is unkeyed: anyone who edits a receipt can compute a new digest, so it shows
that a receipt is internally consistent, not who issued it. Signing it is the
next step. What a receipt adds over a hash is that the decision can be run
again: with the same sources, replay() must arrive at the same digest.

created_at sits outside the digest on purpose: the same inputs must give the
same digest on any day.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from .facts import Fact, Label, Source

# 0.2: the anchoring check, and its switch recorded in each receipt's policy.
# 0.3: each fact says whether it was given or computed here, and from what.
RECIPE = "antihallucination/0.3"
_OUTSIDE_DIGEST = frozenset({"digest", "created_at", "signature"})


def canonical_number(value: Decimal) -> str:
    """A number as a plain decimal string: no exponent, no float rounding.

    The decimals written are kept («0.00» stays «0.00»): they decide how the
    figure is rendered, and a replay must render it the same way. Only the
    sign of zero goes, as JSON and most languages drop it.
    """
    if value.is_zero():
        value = value.copy_abs()
    return format(value, "f")


def _sha256(data: object) -> str:
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def digest(body: Mapping[str, object]) -> str:
    """The digest of a receipt body (every field except digest, created_at and signature)."""
    return _sha256({key: value for key, value in body.items() if key not in _OUTSIDE_DIGEST})


def fact_record(fact: Fact) -> dict[str, object]:
    """A fact as the receipt keeps it. `derived` is null for a figure you gave,
    or how this package computed it: {"compute", "from", "to"}."""
    return {
        "name": fact.name,
        "value": canonical_number(fact.number),
        "unit": fact.unit,
        "decimals": fact.decimals,
        "label": fact.label,
        "subject": list(fact.subjects),
        "change": fact.change,
        "signed": fact.signed,
        "compact": fact.compact,
        "derived": fact.derived.to_dict() if fact.derived else None,
    }


def label_record(label: Label) -> dict[str, object]:
    return {"name": label.name, "text": label.text, "rule": label.rule}


def source_record(source: Source) -> dict[str, object]:
    """A source by its id and a hash of everything the writer read: the text stays with you."""
    content = {
        "id": source.id,
        "name": source.name,
        "title": source.title,
        "text": source.text,
        "fallback": source.fallback,
    }
    return {"id": source.id, "name": source.name, "title": source.title, "sha256": _sha256(content)}


@dataclass(frozen=True)
class Receipt:
    body: Mapping[str, object]
    digest: str
    created_at: str

    @classmethod
    def issue(cls, body: Mapping[str, object]) -> "Receipt":
        stamp = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        return cls(body=dict(body), digest=digest(body), created_at=stamp)

    def to_dict(self) -> dict[str, object]:
        return {**self.body, "digest": self.digest, "created_at": self.created_at}

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=False)


class ReceiptStatus(Enum):
    VERIFIED = "verified"  # the digest matches the receipt's content
    MISMATCH = "mismatch"  # the content changed after the digest was computed
    UNREADABLE = "unreadable"  # not a receipt this recipe can read


@dataclass(frozen=True)
class ReceiptCheck:
    status: ReceiptStatus
    reason: str = ""


def load(receipt: "Receipt | Mapping[str, object] | str") -> dict[str, object]:
    """A receipt as a plain dict, from the object, its dict or its JSON."""
    if isinstance(receipt, Receipt):
        return receipt.to_dict()
    if isinstance(receipt, str):
        data: object = json.loads(receipt)
    else:
        data = dict(receipt)
    if not isinstance(data, dict) or not all(isinstance(key, str) for key in data):
        raise ValueError("a receipt is a JSON object")
    return {str(key): value for key, value in data.items()}


def verify_receipt(receipt: "Receipt | Mapping[str, object] | str") -> ReceiptCheck:
    """Recompute the digest from the receipt's content and compare.

    VERIFIED says the content is what was digested. It does not say who wrote
    the receipt, nor that the decisions were right: replay() runs them again.
    """
    try:
        data = load(receipt)
    except (ValueError, TypeError) as exc:
        return ReceiptCheck(ReceiptStatus.UNREADABLE, str(exc))
    claimed = data.get("digest")
    if not isinstance(claimed, str) or not claimed.startswith("sha256:"):
        return ReceiptCheck(ReceiptStatus.UNREADABLE, "the receipt carries no sha256 digest")
    if data.get("recipe") != RECIPE:
        return ReceiptCheck(ReceiptStatus.UNREADABLE, f"recipe {data.get('recipe')!r} is not {RECIPE}")
    try:
        recomputed = digest(data)
    except (TypeError, ValueError) as exc:
        return ReceiptCheck(ReceiptStatus.UNREADABLE, f"the content cannot be serialized: {exc}")
    if recomputed != claimed:
        return ReceiptCheck(ReceiptStatus.MISMATCH, "the content does not match its digest")
    return ReceiptCheck(ReceiptStatus.VERIFIED)
