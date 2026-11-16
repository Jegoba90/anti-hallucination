"""Claude as the writer, through the official Anthropic SDK.

    pip install anthropic

Credentials come the way the SDK resolves them: ANTHROPIC_API_KEY, or a
profile from `ant auth login`. The request runs Claude Opus 5.5 by default,
with its adaptive thinking (always on for that model) at effort "high", and
the server-side fallback on: if the model declines a request, the API runs it
again on a fallback model chosen by the refusal's category. served_by says
which model wrote the last draft. No sampling parameters are sent: the API
version the SDK uses rejects them.
"""

from typing import TYPE_CHECKING, Literal

from ..errors import WriterError

if TYPE_CHECKING:
    import anthropic

DEFAULT_MODEL = "claude-opus-5-5"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeWriter:
    """A writer that asks Claude for the draft."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        effort: Effort = "high",
        max_tokens: int = 16000,
        client: "anthropic.Anthropic | None" = None,
    ) -> None:
        if client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise WriterError("ClaudeWriter needs the Anthropic SDK: pip install anthropic") from exc
            client = anthropic.Anthropic()
        self._client = client
        self.model = model
        self.effort: Effort = effort
        self.max_tokens = max_tokens
        self.name = f"anthropic:{model}"
        self.served_by = ""

    def __call__(self, system: str, prompt: str) -> str:
        import anthropic
        from anthropic.types.beta import BetaTextBlock

        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": self.effort},
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.CredentialsError as exc:
            # The client builds without credentials and fails at the first request.
            raise WriterError("no Claude credentials found: set ANTHROPIC_API_KEY or run `ant auth login`") from exc
        except anthropic.AuthenticationError as exc:
            raise WriterError("Claude rejected the credentials: set ANTHROPIC_API_KEY or run `ant auth login`") from exc
        except anthropic.PermissionDeniedError as exc:
            raise WriterError(f"this key may not use {self.model}: {exc.message}") from exc
        except anthropic.NotFoundError as exc:
            raise WriterError(f"Claude does not know the model {self.model!r}") from exc
        except anthropic.RateLimitError as exc:
            raise WriterError("Claude's rate limit was reached; try again later") from exc
        except anthropic.APIStatusError as exc:
            raise WriterError(f"Claude answered {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise WriterError("could not reach the Claude API") from exc
        except anthropic.AnthropicError as exc:
            # Anything else the SDK raises, after the specific cases above.
            raise WriterError(f"the Anthropic SDK failed: {exc}") from exc

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise WriterError(f"Claude declined to write this text ({category or 'no category given'})")
        if response.stop_reason == "max_tokens":
            raise WriterError("the draft was cut off at max_tokens")
        self.served_by = str(response.model)
        return "".join(block.text for block in response.content if isinstance(block, BetaTextBlock)).strip()
