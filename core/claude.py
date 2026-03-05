import asyncio
import json as _json
import time
from typing import AsyncGenerator, Optional

import anthropic

from config import settings
from core.log import get_logger
from core.tool_executor import ToolExecutor

logger = get_logger("core.claude")

MAX_TOOL_ROUNDS = 15
MAX_TOKENS_RESPONSE = 4096
MAX_TOKENS_CLASSIFY = 256


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
        tool_executor: ToolExecutor | None = None,
        max_iterations: int = None,
        agent_name: str = "",
    ) -> str:
        if max_iterations is None:
            max_iterations = settings.MAX_AGENT_ITERATIONS

        executor = tool_executor or self.tool_executor

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

        # Metrics accumulators
        total_tool_calls = 0
        total_tool_errors = 0
        total_input_tokens = 0
        total_output_tokens = 0

        for iteration in range(max_iterations):
            response = await self._call_api(model, system, cached_tools, messages)
            if response is None:
                return "I'm experiencing a temporary issue. Please try again."

            # Accumulate token usage
            if hasattr(response, "usage") and response.usage:
                total_input_tokens += getattr(response.usage, "input_tokens", 0)
                total_output_tokens += getattr(response.usage, "output_tokens", 0)

            logger.debug("iteration %d/%d | stop_reason=%s", iteration + 1, max_iterations, response.stop_reason)

            if response.stop_reason == "end_turn":
                self._emit_metrics(agent_name, total_tool_calls, total_tool_errors, total_input_tokens, total_output_tokens)
                return self._extract_text(response)

            if response.stop_reason == "tool_use":
                messages.append({
                    "role": "assistant",
                    "content": self._serialize_content(response.content),
                })

                # Collect all tool_use blocks and execute in parallel
                tool_blocks = [b for b in response.content if b.type == "tool_use"]
                total_tool_calls += len(tool_blocks)

                for b in tool_blocks:
                    logger.info("tool call: %s | input=%s", b.name, b.input)

                results = await asyncio.gather(*[
                    executor.execute(b.name, b.input, user_id)
                    for b in tool_blocks
                ], return_exceptions=True)

                tool_results = []
                for block, result in zip(tool_blocks, results):
                    if isinstance(result, Exception):
                        logger.warning("tool %s failed: %s", block.name, result)
                        total_tool_errors += 1
                        result = f"Error executing {block.name}: {result}"
                    elif str(result).startswith("Error"):
                        total_tool_errors += 1
                    logger.debug("tool result: %s → %s", block.name, str(result)[:300])
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })

                messages.append({"role": "user", "content": tool_results})
                continue

            self._emit_metrics(agent_name, total_tool_calls, total_tool_errors, total_input_tokens, total_output_tokens)
            return self._extract_text(response)

        self._emit_metrics(agent_name, total_tool_calls, total_tool_errors, total_input_tokens, total_output_tokens)
        return "I'm having trouble processing this request. Could you rephrase?"

    @staticmethod
    def _emit_metrics(agent_name: str, tool_calls: int, tool_errors: int, tokens_in: int, tokens_out: int):
        """Fire-and-forget metrics to Redis."""
        if not agent_name:
            return
        try:
            from db.redis_store import track_agent_metrics
            track_agent_metrics(
                agent_name,
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
            )
        except Exception as e:
            logger.debug("metrics emit failed (non-critical): %s", e)

    # ------------------------------------------------------------------
    # Streaming variant — yields SSE event dicts
    # ------------------------------------------------------------------

    async def run_agent_stream(
        self,
        system_prompt: str,
        tools: list[dict],
        messages: list[dict],
        model: str,
        user_id: str,
        tool_executor: ToolExecutor | None = None,
        max_iterations: int | None = None,
        agent_name: str = "",
    ) -> AsyncGenerator[dict, None]:
        """Streaming version of run_agent. Yields dicts like
        {"event": "content_delta", "data": {"text": "…"}} that the
        caller serialises as SSE frames.
        """
        if max_iterations is None:
            max_iterations = settings.MAX_AGENT_ITERATIONS

        executor = tool_executor or self.tool_executor

        # Metrics accumulators
        total_tool_calls = 0
        total_tool_errors = 0
        total_input_tokens = 0
        total_output_tokens = 0

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
            logger.debug("stream iteration %d/%d", iteration + 1, max_iterations)

            kwargs = {
                "model": model,
                "max_tokens": MAX_TOKENS_RESPONSE,
                "system": system,
                "messages": messages,
            }
            if cached_tools:
                kwargs["tools"] = cached_tools

            # Track tool-use blocks built from deltas
            current_tool_id: str | None = None
            current_tool_name: str | None = None
            current_tool_json = ""

            try:
                async with self.client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        # -- text deltas --
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                yield {"event": "content_delta", "data": {"text": event.delta.text}}
                            elif hasattr(event.delta, "partial_json"):
                                current_tool_json += event.delta.partial_json

                        # -- block boundaries --
                        elif event.type == "content_block_start":
                            block = event.content_block
                            if block.type == "tool_use":
                                current_tool_id = block.id
                                current_tool_name = block.name
                                current_tool_json = ""
                                logger.info("stream tool call: %s", block.name)
                                yield {"event": "tool_start", "data": {"tool": block.name}}

                        elif event.type == "content_block_stop":
                            # Reset per-block trackers (tool input fully received)
                            current_tool_id = None
                            current_tool_name = None
                            current_tool_json = ""

                    # Get fully-assembled response for the tool-use loop
                    response = await stream.get_final_message()

            except anthropic.RateLimitError:
                logger.warning("rate limited during stream")
                await asyncio.sleep(2)
                continue
            except anthropic.APIError as e:
                logger.error("API error during stream: %s", e)
                yield {"event": "error", "data": {"text": "I'm experiencing a temporary issue. Please try again."}}
                return

            if response is None:
                yield {"event": "error", "data": {"text": "I'm experiencing a temporary issue. Please try again."}}
                return

            logger.debug("stream stop_reason=%s", response.stop_reason)

            # Accumulate token usage
            if hasattr(response, "usage") and response.usage:
                total_input_tokens += getattr(response.usage, "input_tokens", 0)
                total_output_tokens += getattr(response.usage, "output_tokens", 0)

            if response.stop_reason == "end_turn":
                self._emit_metrics(agent_name, total_tool_calls, total_tool_errors, total_input_tokens, total_output_tokens)
                return  # all text already streamed via content_delta events

            if response.stop_reason == "tool_use":
                # Append assistant turn so the loop can continue
                messages.append({
                    "role": "assistant",
                    "content": self._serialize_content(response.content),
                })

                # Execute all tool calls in parallel
                tool_blocks = [b for b in response.content if b.type == "tool_use"]
                total_tool_calls += len(tool_blocks)

                results = await asyncio.gather(*[
                    executor.execute(b.name, b.input, user_id)
                    for b in tool_blocks
                ], return_exceptions=True)

                tool_results = []
                for block, result in zip(tool_blocks, results):
                    if isinstance(result, Exception):
                        logger.warning("stream tool %s failed: %s", block.name, result)
                        total_tool_errors += 1
                        result = f"Error executing {block.name}: {result}"
                    elif str(result).startswith("Error"):
                        total_tool_errors += 1
                    logger.debug("stream tool result: %s → %s", block.name, str(result)[:200])
                    yield {"event": "tool_done", "data": {"tool": block.name}}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })

                messages.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — text was already streamed
            self._emit_metrics(agent_name, total_tool_calls, total_tool_errors, total_input_tokens, total_output_tokens)
            return

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
                    max_tokens=MAX_TOKENS_CLASSIFY,
                    system=system,
                    messages=messages,
                )
                text = self._extract_text(response)
                if text:
                    import json
                    cleaned = self._clean_json(text)
                    logger.debug("classify raw=%s → cleaned=%s", repr(text[:80]), repr(cleaned))
                    return json.loads(cleaned)
            except Exception as e:
                logger.warning("classify attempt %d failed: %s", attempt + 1, e)
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
                    "max_tokens": MAX_TOKENS_RESPONSE,
                    "system": system,
                    "messages": messages,
                }
                if tools:
                    kwargs["tools"] = tools
                return await self.client.messages.create(**kwargs)
            except anthropic.RateLimitError:
                wait = 2 ** attempt
                logger.warning("rate limited, waiting %ds", wait)
                await asyncio.sleep(wait)
            except anthropic.APIError as e:
                logger.error("API error: %s", e)
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
