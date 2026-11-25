from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class Done:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict


class Provider(ABC):
    name: str

    @abstractmethod
    def stream(self, *, model: str, system: str, messages: list[dict], tools: list[ToolSpec],
               api_key: str, max_tokens: int) -> AsyncIterator: ...

    @abstractmethod
    async def list_models(self, api_key: str) -> list[str]: ...
