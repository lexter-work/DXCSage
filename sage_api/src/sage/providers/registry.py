from sage.providers.anthropic_provider import AnthropicProvider
from sage.providers.base import Provider
from sage.providers.openai_provider import OpenAIProvider


def default_providers() -> dict[str, Provider]:
    return {"anthropic": AnthropicProvider(), "openai": OpenAIProvider()}
