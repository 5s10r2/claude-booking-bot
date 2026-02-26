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
