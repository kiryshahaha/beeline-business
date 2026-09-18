"""Minimal Ollama chat client with the timing numbers Ollama reports."""

from dataclasses import dataclass

import httpx

_NANOSECONDS = 1_000_000_000


class LlmUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class LlmReply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    load_seconds: float
    prompt_seconds: float
    generation_seconds: float
    total_seconds: float

    @property
    def tokens_per_second(self) -> float:
        return self.completion_tokens / self.generation_seconds if self.generation_seconds else 0.0


class OllamaClient:
    def __init__(self, base_url: str, timeout_seconds: float):
        self._client = httpx.Client(base_url=base_url, timeout=timeout_seconds)

    def chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        num_ctx: int,
        max_tokens: int,
        num_thread: int | None = None,
    ) -> LlmReply:
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            # Qwen3 and Qwen3.5 are hybrid reasoning models; short onboarding answers
            # do not need a thinking pass, which would multiply latency on CPU.
            "think": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.8,
                "top_k": 20,
                "repeat_penalty": 1.1,
                "num_ctx": num_ctx,
                "num_predict": max_tokens,
            },
        }
        if num_thread:
            payload["options"]["num_thread"] = num_thread
        try:
            response = self._client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise LlmUnavailableError(str(error)) from error
        data = response.json()
        return LlmReply(
            text=data["message"]["content"].strip(),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            load_seconds=data.get("load_duration", 0) / _NANOSECONDS,
            prompt_seconds=data.get("prompt_eval_duration", 0) / _NANOSECONDS,
            generation_seconds=data.get("eval_duration", 0) / _NANOSECONDS,
            total_seconds=data.get("total_duration", 0) / _NANOSECONDS,
        )

    def close(self) -> None:
        self._client.close()
