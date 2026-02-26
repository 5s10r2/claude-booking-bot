import asyncio
import time
from typing import Optional

import anthropic

from config import settings
from core.tool_executor import ToolExecutor


class AnthropicEngine:
    def __init__(self, tool_executor: ToolExecutor):
        self.client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.tool_executor = tool_executor

    async def run_agent(
        self,
        system_prompt: str,
        tools: list[dict],
        messages: list[dict],
        model: str,
        user_id: str,
        max_iterations: int = None,
    ) -> str:
        if max_iterations is None:
            max_iterations = settings.MAX_AGENT_ITERATIONS

        system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        cached_tools = []
        for i, tool in enumerate(tools):
            t = dict(tool)
            if i == len(tools) - 1:
                t["cache_control"] = {"type": "ephemeral"}
            cached_tools.append(t)

        for iteration in range(max_iterations):
            response = await self._call_api(model, system, cached_tools, messages)
            if response is None:
                return "I'm experiencing a temporary issue. Please try again."

            print(f"[agent] iteration {iteration + 1}/{max_iterations} | stop_reason: {response.stop_reason}")

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            if response.stop_reason == "tool_use":
                messages.append({
                    "role": "assistant",
                    "content": self._serialize_content(response.content),
                })

                # Collect all tool_use blocks and execute in parallel
                tool_blocks = [b for b in response.content if b.type == "tool_use"]

                for b in tool_blocks:
                    print(f"[tool] calling: {b.name} | input: {b.input}")

                results = await asyncio.gather(*[
                    self.tool_executor.execute(b.name, b.input, user_id)
                    for b in tool_blocks
                ])

                tool_results = []
                for block, result in zip(tool_blocks, results):
                    print(f"[tool] result: {block.name} → {str(result)[:300]}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })

                messages.append({"role": "user", "content": tool_results})
                continue

            return self._extract_text(response)

        return "I'm having trouble processing this request. Could you rephrase?"

    async def classify(
        self,
        system_prompt: str,
        messages: list[dict],
        model: str,
    ) -> Optional[dict]:
        """Single-turn classification (supervisor routing). No tool loop."""
        system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        for attempt in range(3):
            try:
                response = await self.client.messages.create(
                    model=model,
                    max_tokens=256,
                    system=system,
                    messages=messages,
                )
                text = self._extract_text(response)
                if text:
                    import json
                    cleaned = self._clean_json(text)
                    print(f"[classify] raw={repr(text[:80])} → cleaned={repr(cleaned)}")
                    return json.loads(cleaned)
            except Exception as e:
                print(f"[claude] classify attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(0.5)
        return None

    async def _call_api(
        self,
        model: str,
        system: list,
        tools: list,
        messages: list,
    ):
        max_retries = 3
        for attempt in range(max_retries):
            try:
                kwargs = {
                    "model": model,
                    "max_tokens": 4096,
                    "system": system,
                    "messages": messages,
                }
                if tools:
                    kwargs["tools"] = tools
                return await self.client.messages.create(**kwargs)
            except anthropic.RateLimitError:
                wait = 2 ** attempt
                print(f"[claude] rate limited, waiting {wait}s...")
                await asyncio.sleep(wait)
            except anthropic.APIError as e:
                print(f"[claude] API error: {e}")
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(1)
        return None

    @staticmethod
    def _extract_text(response) -> str:
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts)

    @staticmethod
    def _clean_json(text: str) -> str:
        """Extract JSON from text that may have markdown fences or extra text."""
        import re
        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```", "", text)
        text = text.strip()
        # If still not starting with {, find the first JSON object
        if not text.startswith("{"):
            match = re.search(r"\{[^{}]*\}", text)
            if match:
                text = match.group(0)
        return text

    @staticmethod
    def _serialize_content(content) -> list[dict]:
        serialized = []
        for block in content:
            if block.type == "text":
                serialized.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                serialized.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return serialized
