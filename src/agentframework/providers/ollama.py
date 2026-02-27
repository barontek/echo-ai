"""Ollama provider implementation."""

import json
from typing import Any, Callable, Optional

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
                content = f"__THINKING__\n{thinking}\n__THINKING_END__\n\n{content}"
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

    async def chat_streaming(
        self,
        messages: list[dict[str, str]],
        tools: Optional[list[dict[str, Any]]] = None,
        temperature: float = 0.3,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> LLMResponse:
        """Send a streaming chat request to Ollama."""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with self.client.stream("POST", "/api/chat", json=payload, headers=headers) as response:
                response.raise_for_status()
                
                content = ""
                thinking = ""
                tool_calls = []
                
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except:
                        continue
                    
                    msg = data.get("message", {})
                    
                    # Handle thinking (stream it with marker)
                    msg_thinking = msg.get("thinking", "")
                    if msg_thinking:
                        # Only send start marker if we haven't started thinking yet
                        if not thinking:
                            if on_chunk:
                                on_chunk("__THINKING__")
                        thinking = msg_thinking
                        if on_chunk:
                            on_chunk(msg_thinking)
                    
                    # Handle content
                    chunk = msg.get("content", "")
                    if chunk:
                        # If we had thinking, add end marker before content
                        if thinking:
                            if on_chunk:
                                on_chunk("__THINKING_END__")
                            thinking = None  # Clear so we don't add again
                        content += chunk
                        if on_chunk:
                            on_chunk(chunk)
                    
                    # Handle tool calls
                    if "tool_calls" in msg:
                        for tc in msg["tool_calls"]:
                            args = tc.get("function", {}).get("arguments", {})
                            if isinstance(args, str):
                                args = json.loads(args)
                            tool_calls.append(LLMToolCall(
                                id=tc.get("id", ""),
                                name=tc.get("function", {}).get("name", ""),
                                arguments=args,
                            ))
                    
                    if data.get("done"):
                        break

            # Combine thinking with content if present
            final_content = content
            if thinking:
                final_content = f"__THINKING__\n{thinking}\n__THINKING_END__\n\n{content}"
            
            return LLMResponse(content=final_content, tool_calls=tool_calls)

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
