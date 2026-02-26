"""Ollama provider implementation."""

import json
from typing import Any

import httpx

from . import LLMProvider, LLMResponse, LLMToolCall


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=120.0,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Send a chat request to Ollama."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }

        if tools:
            payload["tools"] = tools

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = await self.client.post(
                "/api/chat",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")
            thinking = data.get("message", {}).get("thinking", "")
            if thinking:
                content = thinking + "\n\n" + content
            tool_calls = []

            if "tool_calls" in data.get("message", {}):
                for tc in data["message"]["tool_calls"]:
                    args = tc.get("function", {}).get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)
                    tool_calls.append(LLMToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=args,
                    ))

            return LLMResponse(content=content, tool_calls=tool_calls)

        except httpx.HTTPStatusError as e:
            return LLMResponse(content=f"HTTP error: {e.response.status_code}")
        except Exception as e:
            return LLMResponse(content=f"Error: {str(e)}")

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    def list_models(self) -> list[str]:
        """List available models (sync)."""
        import httpx
        try:
            response = httpx.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
