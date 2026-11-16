"""Any model behind the OpenAI chat-completions protocol, as the writer.

OpenAI itself, Groq, Ollama and LM Studio on your machine, vLLM, and most
gateways speak the same POST /chat/completions. This talks it over plain HTTP
with httpx, so no provider SDK is needed. Name the model: there is no default,
because only you know which one your server runs.

    OpenAICompatibleWriter.openai("model-name")   # OPENAI_API_KEY
    OpenAICompatibleWriter.groq("model-name")     # GROQ_API_KEY
    OpenAICompatibleWriter.ollama("model-name")   # a local Ollama, no key
"""

import json
import os

import httpx

from ..errors import WriterError

OPENAI_BASE_URL = "https://api.openai.com/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"


class OpenAICompatibleWriter:
    """A writer that asks an OpenAI-compatible server for the draft."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = OPENAI_BASE_URL,
        api_key: str | None = None,
        api_key_env: str | None = "OPENAI_API_KEY",
        provider: str = "openai",
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """api_key wins over api_key_env; with neither, no key is sent (a local server)."""
        if not model or not model.strip():
            raise ValueError("name the model the server should run")
        key = api_key if api_key is not None else (os.environ.get(api_key_env) if api_key_env else None)
        if api_key_env and not key:
            raise WriterError(f"{provider} needs a key: set {api_key_env}")
        self.model = model.strip()
        self.base_url = base_url.rstrip("/")
        self.provider = provider
        self.name = f"{provider}:{self.model}"
        self.served_by = ""
        self._headers = {"Authorization": f"Bearer {key}"} if key else {}
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def openai(cls, model: str, **options: object) -> "OpenAICompatibleWriter":
        return cls._preset(model, OPENAI_BASE_URL, "OPENAI_API_KEY", "openai", options)

    @classmethod
    def groq(cls, model: str, **options: object) -> "OpenAICompatibleWriter":
        return cls._preset(model, GROQ_BASE_URL, "GROQ_API_KEY", "groq", options)

    @classmethod
    def ollama(cls, model: str, **options: object) -> "OpenAICompatibleWriter":
        return cls._preset(model, OLLAMA_BASE_URL, None, "ollama", options)

    @classmethod
    def _preset(
        cls, model: str, base_url: str, api_key_env: str | None, provider: str, options: dict[str, object]
    ) -> "OpenAICompatibleWriter":
        url = options.pop("base_url", base_url)
        key = options.pop("api_key", None)
        transport = options.pop("transport", None)
        if options:
            raise TypeError(f"unexpected options: {', '.join(options)}")
        if not isinstance(url, str) or not (key is None or isinstance(key, str)):
            raise TypeError("base_url and api_key must be text")
        if transport is not None and not isinstance(transport, httpx.BaseTransport):
            raise TypeError("transport must be an httpx transport")
        return cls(model, base_url=url, api_key=key, api_key_env=api_key_env, provider=provider, transport=transport)

    def __call__(self, system: str, prompt: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise WriterError(f"could not reach {self.base_url}: {exc}") from exc
        payload = _json(response)
        if not response.is_success:
            raise WriterError(f"{self.provider} answered {response.status_code}: {_error_message(payload)}")
        choice = _first_choice(payload)
        if choice.get("finish_reason") == "length":
            raise WriterError("the draft was cut off at the token limit")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise WriterError(f"{self.provider} returned no text")
        model = payload.get("model") if isinstance(payload, dict) else None
        self.served_by = model if isinstance(model, str) else ""
        return content.strip()


def _json(response: httpx.Response) -> object:
    try:
        payload: object = json.loads(response.content)
    except ValueError:
        return None
    return payload


def _error_message(payload: object) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(error, str):
            return error
    return "no explanation in the body"


def _first_choice(payload: object) -> dict[str, object]:
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise WriterError("the server returned no choices")
    return {str(key): value for key, value in choices[0].items()}
