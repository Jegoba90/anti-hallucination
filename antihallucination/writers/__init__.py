"""Ready-made writers. Each provider lives in its own module.

ClaudeWriter needs `pip install anthropic`, and imports it only when built.
OpenAICompatibleWriter needs httpx, which the repository already requires.
Any function (system, prompt) -> str is a writer too.
"""

from ..errors import WriterError
from .claude import ClaudeWriter
from .openai_compatible import OpenAICompatibleWriter

__all__ = ["ClaudeWriter", "OpenAICompatibleWriter", "WriterError"]
