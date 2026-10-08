from typing import Protocol


class LLMClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        ...


class FakeLLM:
    def complete(self, messages: list[dict[str, str]]) -> str:
        return "fake response"