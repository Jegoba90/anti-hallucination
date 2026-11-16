"""OpenAICompatibleWriter sends a standard chat completion and fails in plain words.

No request leaves the machine: it runs on an httpx MockTransport. What is
pinned is the request it builds for OpenAI, Groq and Ollama, and how each
failure reads. ClaudeWriter has its own file, since its SDK is optional.
"""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from antihallucination.errors import WriterError
from antihallucination.writers.openai_compatible import (
    GROQ_BASE_URL,
    OLLAMA_BASE_URL,
    OpenAICompatibleWriter,
)


def _server(status: int = 200, body: object = None, seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    reply = body if body is not None else {
        "model": "served-model",
        "choices": [{"message": {"role": "assistant", "content": "  Hola.  "}, "finish_reason": "stop"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=json.dumps(reply))

    return httpx.MockTransport(handler)


class TestOpenAICompatible:
    def test_it_posts_a_chat_completion_with_both_prompts(self) -> None:
        seen: list[httpx.Request] = []
        writer = OpenAICompatibleWriter("m1", api_key="k", transport=_server(seen=seen))

        assert writer("SYSTEM", "PROMPT") == "Hola."
        request = seen[0]
        assert str(request.url) == "https://api.openai.com/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer k"
        assert json.loads(request.content) == {
            "model": "m1",
            "messages": [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "PROMPT"}],
        }
        assert writer.served_by == "served-model"

    def test_groq_reads_its_own_key_and_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GROQ_API_KEY", "gk")
        seen: list[httpx.Request] = []
        writer = OpenAICompatibleWriter.groq("m2", transport=_server(seen=seen))
        writer("s", "p")

        assert str(seen[0].url) == f"{GROQ_BASE_URL}/chat/completions"
        assert seen[0].headers["authorization"] == "Bearer gk"
        assert writer.name == "groq:m2"

    def test_ollama_needs_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        seen: list[httpx.Request] = []
        OpenAICompatibleWriter.ollama("llama", transport=_server(seen=seen))("s", "p")

        assert str(seen[0].url) == f"{OLLAMA_BASE_URL}/chat/completions"
        assert "authorization" not in seen[0].headers

    def test_a_missing_key_fails_before_any_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(WriterError, match="OPENAI_API_KEY"):
            OpenAICompatibleWriter.openai("m1")

    def test_a_model_must_be_named(self) -> None:
        with pytest.raises(ValueError):
            OpenAICompatibleWriter("", api_key="k")

    @pytest.mark.parametrize(
        ("status", "body", "message"),
        [
            (401, {"error": {"message": "Invalid API key"}}, "answered 401: Invalid API key"),
            (200, {"choices": []}, "no choices"),
            (200, {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]}, "cut off"),
            (200, {"choices": [{"message": {"content": None}}]}, "no text"),
        ],
    )
    def test_each_failure_reads_plainly(self, status: int, body: object, message: str) -> None:
        writer = OpenAICompatibleWriter("m1", api_key="k", transport=_server(status, body))

        with pytest.raises(WriterError, match=message):
            writer("s", "p")

    def test_an_unreachable_server_is_a_writer_error(self) -> None:
        def down(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        writer = OpenAICompatibleWriter("m1", api_key="k", transport=httpx.MockTransport(down))

        with pytest.raises(WriterError, match="could not reach"):
            writer("s", "p")
