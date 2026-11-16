"""ClaudeWriter sends the request the current Claude API expects, and fails in plain words.

No request leaves the machine: a stand-in client with the SDK's shape records
the call. Skipped where the Anthropic SDK is not installed (the CI job that
installs only the declared floors): the SDK is optional, needed only to write
with Claude.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

anthropic = pytest.importorskip("anthropic")
from anthropic.types.beta import BetaTextBlock  # noqa: E402

from antihallucination.errors import WriterError  # noqa: E402
from antihallucination.writers.claude import DEFAULT_MODEL, ClaudeWriter  # noqa: E402


class _Messages:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _client(outcome: object) -> tuple[object, _Messages]:
    messages = _Messages(outcome)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def _reply(text: str = "Hola.", stop_reason: str = "end_turn", stop_details: object = None) -> object:
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=stop_details,
        model="claude-opus-5-5",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            BetaTextBlock(type="text", text=f"  {text}"),
            BetaTextBlock(type="text", text=" Chau. "),
        ],
    )


class TestClaude:
    def test_the_request_follows_the_current_api(self) -> None:
        client, messages = _client(_reply())
        writer = ClaudeWriter(client=client)  # type: ignore[arg-type]

        assert writer("SYSTEM", "PROMPT") == "Hola. Chau."
        call = messages.calls[0]
        assert call["model"] == DEFAULT_MODEL == "claude-opus-5-5"
        assert call["system"] == "SYSTEM"
        assert call["messages"] == [{"role": "user", "content": "PROMPT"}]
        assert call["output_config"] == {"effort": "high"}
        assert call["betas"] == ["server-side-fallback-2026-07-01"]
        assert call["fallbacks"] == "default"
        assert not {"temperature", "top_p", "top_k"} & set(call)
        assert writer.served_by == "claude-opus-5-5"

    def test_a_refusal_is_an_error_with_its_category(self) -> None:
        details = SimpleNamespace(category="cyber", explanation="...")
        client, _ = _client(_reply(stop_reason="refusal", stop_details=details))

        with pytest.raises(WriterError, match="declined.*cyber"):
            ClaudeWriter(client=client)("s", "p")  # type: ignore[arg-type]

    def test_a_cut_off_draft_is_an_error(self) -> None:
        client, _ = _client(_reply(stop_reason="max_tokens"))

        with pytest.raises(WriterError, match="max_tokens"):
            ClaudeWriter(client=client)("s", "p")  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            ("AuthenticationError", "credentials"),
            ("RateLimitError", "rate limit"),
            ("InternalServerError", "answered 500"),
        ],
    )
    def test_sdk_errors_read_plainly(self, error: str, message: str) -> None:
        import httpx2

        status = {"AuthenticationError": 401, "RateLimitError": 429, "InternalServerError": 500}[error]
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx2.Response(status, request=request)
        exception = getattr(anthropic, error)("boom", response=response, body=None)
        client, _ = _client(exception)

        with pytest.raises(WriterError, match=message):
            ClaudeWriter(client=client)("s", "p")  # type: ignore[arg-type]

    def test_missing_credentials_read_plainly(self) -> None:
        """The SDK builds a client without credentials and raises at the first request."""
        client, _ = _client(anthropic.CredentialsError("no credentials found"))

        with pytest.raises(WriterError, match="no Claude credentials found"):
            ClaudeWriter(client=client)("s", "p")  # type: ignore[arg-type]

    def test_any_other_sdk_error_is_still_a_writer_error(self) -> None:
        client, _ = _client(anthropic.AnthropicError("unexpected"))

        with pytest.raises(WriterError, match="the Anthropic SDK failed: unexpected"):
            ClaudeWriter(client=client)("s", "p")  # type: ignore[arg-type]

    def test_without_the_sdk_it_says_how_to_install_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "anthropic", None)

        with pytest.raises(WriterError, match="pip install anthropic"):
            ClaudeWriter()
