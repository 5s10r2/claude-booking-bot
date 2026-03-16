"""
Nomic Atlas embedding client for semantic KB retrieval.

Uses nomic-embed-text-v1.5 via raw HTTP (no SDK dependency).
All functions return None on any failure — callers fall back to old behaviour.

Env: NOMIC_API_KEY (required), SEMANTIC_KB_ENABLED=true (feature flag).
"""

import httpx

from config import settings
from core.log import get_logger

logger = get_logger("utils.embeddings")

_API_URL = "https://api-atlas.nomic.ai/v1/embedding/text"
_MODEL = "nomic-embed-text-v1.5"
_DIMS = 256  # Matryoshka truncation — 98%+ quality at 33% storage
_TIMEOUT = 15.0  # seconds


def _is_enabled() -> bool:
    """Check both feature flag and API key are set."""
    return bool(settings.SEMANTIC_KB_ENABLED and settings.NOMIC_API_KEY)


async def _call_nomic(
    texts: list[str],
    task_type: str,
) -> list[list[float]] | None:
    """POST to Nomic Atlas embedding API. Returns list of vectors or None."""
    if not _is_enabled():
        return None
    if not texts:
        return None

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {settings.NOMIC_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "texts": texts,
                    "task_type": task_type,
                    "dimensionality": _DIMS,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Response format: {"embeddings": [[...], [...]], ...}
            embeddings = data.get("embeddings")
            if not embeddings or len(embeddings) != len(texts):
                logger.warning("Nomic API returned unexpected shape: %s embeddings for %s texts", len(embeddings) if embeddings else 0, len(texts))
                return None

            return embeddings

    except httpx.TimeoutException:
        logger.warning("Nomic API timeout after %.0fs", _TIMEOUT)
        return None
    except httpx.HTTPStatusError as e:
        logger.warning("Nomic API HTTP %s: %s", e.response.status_code, e.response.text[:200])
        return None
    except Exception as e:
        logger.warning("Nomic API error: %s", e)
        return None


async def embed_documents(texts: list[str]) -> list[list[float]] | None:
    """Embed documents for indexing (search_document task).

    Returns list of 256-dim vectors, one per input text.
    Returns None on any failure.
    """
    return await _call_nomic(texts, task_type="search_document")


async def embed_query(text: str) -> list[float] | None:
    """Embed a user query for retrieval (search_query task).

    Returns a single 256-dim vector, or None on failure.
    """
    result = await _call_nomic([text], task_type="search_query")
    if result and len(result) == 1:
        return result[0]
    return None
