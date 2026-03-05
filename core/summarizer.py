"""
summarizer.py — Claude-powered conversation summarization.

Replaces blind 40-message truncation with structured summarization that
preserves all decision context: preferences, property states, booking
progress, rejections + reasons, and conversational momentum.

Quality target: match Claude Code's auto-compaction — compress tool-heavy
conversations into dense structured summaries without losing any signal
that affects future responses.
"""

import anthropic
from config import settings
from core.log import get_logger

logger = get_logger("core.summarizer")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SUMMARIZE_THRESHOLD = getattr(settings, "SUMMARIZE_THRESHOLD", 30)
KEEP_RECENT = getattr(settings, "SUMMARIZE_KEEP_RECENT", 10)
SUMMARY_TAG_OPEN = "[CONVERSATION_SUMMARY]"
SUMMARY_TAG_CLOSE = "[/CONVERSATION_SUMMARY]"
MAX_TOOL_RESULT_CHARS = 300  # truncate long tool results before summarizing
COMPACT_THRESHOLD = 500  # compact tool results larger than this (chars)
KEEP_RECENT_FOR_COMPACT = 6  # keep this many recent messages untouched

# ---------------------------------------------------------------------------
# Tool result compaction (runs BEFORE summarization)
# ---------------------------------------------------------------------------


def _find_tool_name(messages: list[dict], tool_use_id: str) -> str:
    """Find the tool name for a tool_use_id by scanning assistant messages."""
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if (isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("id") == tool_use_id):
                return block.get("name", "")
    return ""


def _compact_result(tool_name: str, content: str) -> str:
    """Generate a compact summary of a tool result based on tool type."""
    if tool_name == "search_properties":
        lines = content.split("\n")
        header = lines[0] if lines else "Search completed"
        names = []
        for line in lines[1:6]:
            if line.startswith("- "):
                name = line.split("|")[0].replace("- ", "").strip()
                if name:
                    names.append(name)
        name_str = ", ".join(names[:5])
        return f"[Compacted] {header}\nTop matches: {name_str}. Full data cached — use property names to reference."

    if tool_name in ("fetch_property_details", "fetch_room_details"):
        return f"[Compacted] {content[:200]}... Full details cached."

    if tool_name == "fetch_property_images":
        url_count = content.count("http")
        return f"[Compacted] {url_count} image URLs retrieved. Cached for display."

    if tool_name in ("fetch_landmarks", "estimate_commute", "fetch_nearby_places"):
        return f"[Compacted] {content[:200]}... Full location data cached."

    if tool_name == "compare_properties":
        return f"[Compacted] Comparison table generated. {content[:150]}..."

    if tool_name == "web_search":
        return f"[Compacted] Web search results: {content[:200]}..."

    # Generic compaction
    return f"[Compacted] {content[:200]}..."


def compact_tool_results(
    messages: list[dict],
    keep_recent: int = KEEP_RECENT_FOR_COMPACT,
) -> list[dict]:
    """Compact verbose tool results in older messages to reduce context size.

    Runs BEFORE summarization. Keeps recent messages untouched since the agent
    may still reference them. For older tool_result blocks exceeding
    COMPACT_THRESHOLD chars, replaces the content with a compact summary that
    preserves just enough info (property names, counts) for continuity.
    """
    if len(messages) <= keep_recent:
        return messages

    older = messages[:-keep_recent]
    recent = messages[-keep_recent:]
    compacted = []
    total_saved = 0

    for msg in older:
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list):
            compacted.append(msg)
            continue

        new_blocks = []
        for block in content:
            if (isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and len(str(block.get("content", ""))) > COMPACT_THRESHOLD):
                tool_name = _find_tool_name(older, block.get("tool_use_id", ""))
                original = str(block.get("content", ""))
                compact = _compact_result(tool_name, original)
                total_saved += len(original) - len(compact)
                new_blocks.append({**block, "content": compact})
            else:
                new_blocks.append(block)

        compacted.append({**msg, "content": new_blocks})

    if total_saved > 0:
        logger.info("compaction saved ~%d chars from older tool results", total_saved)

    return compacted + recent


# Tools that belong to the broker agent — their results are noise for other agents
_BROKER_TOOLS = {
    "search_properties", "fetch_property_details", "fetch_room_details",
    "fetch_property_images", "fetch_landmarks", "estimate_commute",
    "fetch_nearby_places", "compare_properties", "shortlist_property",
    "save_preferences", "fetch_properties_by_query",
}


def scope_messages_for_agent(messages: list[dict], agent_name: str) -> list[dict]:
    """Apply agent-specific context scoping.

    Broker agent gets messages as-is (it needs full property data).
    Other agents get more aggressive compaction of broker tool results
    since they never reference property JSON directly.

    Returns a new list — does NOT modify the stored conversation.
    """
    if agent_name == "broker":
        return messages

    AGGRESSIVE_THRESHOLD = 200
    scoped = []
    total_saved = 0

    for msg in messages:
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list):
            scoped.append(msg)
            continue

        new_blocks = []
        for block in content:
            if (isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and len(str(block.get("content", ""))) > AGGRESSIVE_THRESHOLD):
                tool_name = _find_tool_name(messages, block.get("tool_use_id", ""))
                if tool_name in _BROKER_TOOLS:
                    original = str(block.get("content", ""))
                    compact = f"[Property data — handled by broker agent. {original[:100]}...]"
                    total_saved += len(original) - len(compact)
                    new_blocks.append({**block, "content": compact})
                else:
                    new_blocks.append(block)
            else:
                new_blocks.append(block)

        scoped.append({**msg, "content": new_blocks})

    if total_saved > 0:
        logger.info("agent scoping (%s) saved ~%d chars from broker tool results", agent_name, total_saved)

    return scoped


# ---------------------------------------------------------------------------
# Summarization prompt
# ---------------------------------------------------------------------------

SUMMARIZER_PROMPT = """\
You are a conversation compactor for a PG/hostel booking assistant. Your job is to \
produce a dense structured summary of an older conversation segment so the assistant \
can continue seamlessly without losing ANY decision-relevant context.

RULES:
- Extract ALL facts, preferences, and decisions — omit nothing that could affect future responses.
- Track every property discussed with its current status and the user's sentiment.
- Preserve rejection reasons verbatim — these prevent re-suggesting rejected options.
- Compress tool call/response pairs into outcomes (e.g., "search returned 12 results near Andheri, top 5 shown").
- Use the exact section headers below. Leave a section empty if nothing applies (write "None").
- Be concise but complete — target ~400-600 tokens total.
- Write in third person ("The user prefers..." not "You prefer...").

OUTPUT FORMAT (use these exact headers):

## User Profile & Preferences
- Name, phone, email (if shared)
- Location/area, city
- Budget range (min–max)
- Gender preference (boys/girls/any)
- Sharing type preference (single/double/triple)
- Amenities requested
- Move-in timeline
- Any other stated preferences

## Properties Discussed
For each property mentioned, one line:
- PropertyName | Status: viewed/shortlisted/rejected/booked | Sentiment: positive/neutral/negative | Key detail or rejection reason

## Booking & Scheduling Status
- Active bookings, scheduled visits, payment status
- KYC status if relevant
- Any pending actions (awaiting callback, payment link sent, etc.)

## Key Decisions & Context
- What the user liked/disliked and why
- Comparisons made and outcomes
- Objections raised and how they were addressed
- Deal-breakers identified

## Current Conversation State
- Last topic discussed
- Likely next action
- Pending questions or items
- User's current mood/urgency level
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_tool_content(content, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    """Truncate tool result content to avoid bloating the summarizer context."""
    if isinstance(content, list):
        # Claude messages with content blocks
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", block.get("content", str(block)))
            else:
                text = str(block)
            if len(text) > max_chars:
                text = text[:max_chars] + f"... [truncated, {len(text)} chars total]"
            parts.append(text)
        return "\n".join(parts)
    text = str(content)
    if len(text) > max_chars:
        return text[:max_chars] + f"... [truncated, {len(text)} chars total]"
    return text


def _format_messages_for_summary(messages: list[dict]) -> str:
    """Format conversation messages into a readable transcript for the summarizer."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")

        # Handle tool_use / tool_result content blocks
        if isinstance(content, list):
            content = _truncate_tool_content(content)
        elif isinstance(content, str) and len(content) > 1000:
            content = content[:1000] + f"... [truncated, {len(content)} chars total]"

        lines.append(f"[{role}]: {content}")
    return "\n\n".join(lines)


def _has_existing_summary(messages: list[dict]) -> bool:
    """Check if the first message pair is already a summary."""
    if len(messages) < 2:
        return False
    first_content = str(messages[0].get("content", ""))
    return SUMMARY_TAG_OPEN in first_content


# ---------------------------------------------------------------------------
# Core summarization
# ---------------------------------------------------------------------------

async def maybe_summarize(messages: list[dict], user_id: str) -> list[dict]:
    """Summarize older messages if conversation exceeds threshold.

    Returns the (potentially compacted) message list:
    - If below threshold: returns messages unchanged
    - If above threshold: returns [summary_user, summary_assistant] + recent messages
    - On error: falls back to plain truncation (current behavior)
    """
    if len(messages) < SUMMARIZE_THRESHOLD:
        return messages

    logger.info(
        "summarization triggered for user %s: %d messages (threshold=%d)",
        user_id, len(messages), SUMMARIZE_THRESHOLD,
    )

    try:
        # Split: older messages to summarize, recent to keep verbatim
        split_point = len(messages) - KEEP_RECENT
        older = messages[:split_point]
        recent = messages[split_point:]

        # If there's an existing summary, include it as context for re-summarization
        existing_summary_note = ""
        if _has_existing_summary(older):
            existing_summary_note = (
                "\n\nNOTE: The conversation already contains a previous summary at the start. "
                "Incorporate that summary's information into your new summary — do not lose any "
                "tracked properties, preferences, or decisions from the previous summary.\n"
            )

        # Format transcript
        transcript = _format_messages_for_summary(older)

        # Call Haiku for summarization
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await client.messages.create(
            model=settings.HAIKU_MODEL,
            max_tokens=800,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{SUMMARIZER_PROMPT}"
                        f"{existing_summary_note}\n\n"
                        f"--- CONVERSATION TO SUMMARIZE ---\n\n"
                        f"{transcript}\n\n"
                        f"--- END OF CONVERSATION ---\n\n"
                        f"Produce the structured summary now."
                    ),
                }
            ],
        )

        summary_text = response.content[0].text.strip()
        logger.info(
            "summarization complete: %d older msgs → %d token summary, keeping %d recent",
            len(older), response.usage.output_tokens, len(recent),
        )

        # Build summary message pair
        summary_user = {
            "role": "user",
            "content": (
                f"{SUMMARY_TAG_OPEN}\n"
                f"The following is a structured summary of our earlier conversation. "
                f"Use this context to maintain continuity.\n\n"
                f"{summary_text}\n"
                f"{SUMMARY_TAG_CLOSE}"
            ),
        }
        summary_assistant = {
            "role": "assistant",
            "content": (
                "I've noted all the context from our earlier conversation. "
                "I'll use this to provide consistent, informed responses. "
                "Please continue — how can I help?"
            ),
        }

        return [summary_user, summary_assistant] + recent

    except Exception as e:
        logger.error("summarization failed, falling back to truncation: %s", e)
        # Fallback: plain truncation (current behavior)
        limit = settings.CONVERSATION_HISTORY_LIMIT * 2
        return messages[-limit:]
