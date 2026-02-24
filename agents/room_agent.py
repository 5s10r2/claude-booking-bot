"""
Room agent: standalone knowledge base Q&A agent.
Uses Haiku for answering questions from the uploaded knowledge base.
"""

from config import settings
from core.claude import AnthropicEngine
from core.prompts import ROOM_AGENT_PROMPT


async def run(
    engine: AnthropicEngine,
    messages: list[dict],
    user_id: str,
    file_hash: str = "",
) -> str:
    # First, query the knowledge base
    from tools.knowledge_base.query_kb import query_knowledge_base

    query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                query = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        query = block.get("text", "")
                        break
            break

    if not query:
        return "Please ask a question about the property or rooms."

    kb_result = await query_knowledge_base(user_id=user_id, query=query, file_hash=file_hash)

    # Use Claude to synthesize the answer from KB results
    augmented_messages = [
        {
            "role": "user",
            "content": f"Knowledge base context:\n{kb_result}\n\nUser question: {query}",
        }
    ]

    response = engine._call_api(
        model=settings.HAIKU_MODEL,
        system=[{"type": "text", "text": ROOM_AGENT_PROMPT}],
        tools=[],
        messages=augmented_messages,
    )

    if response is None:
        return kb_result  # Fallback to raw KB results

    return engine._extract_text(response)
