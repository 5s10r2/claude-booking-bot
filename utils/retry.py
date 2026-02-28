"""Async retry logic for transient HTTP failures.

Two usage patterns:

1. Decorator (wrap entire async functions):
    from utils.retry import with_retry

    @with_retry(max_retries=2, backoff_base=1.0)
    async def call_api():
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

2. Helper functions (drop-in replacements for httpx):
    from utils.retry import http_get, http_post

    data = await http_get(url, params={...})          # returns parsed JSON
    data = await http_post(url, json={...})           # returns parsed JSON
    resp = await http_get(url, raw=True)              # returns httpx.Response
"""

import asyncio
import functools

import httpx

from core.log import get_logger

logger = get_logger("utils.retry")

# Only retry on transient errors — not client errors (4xx)
_RETRYABLE = (
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)

_DEFAULT_TIMEOUT = 15
_DEFAULT_RETRIES = 2
_DEFAULT_BACKOFF = 1.0


def _is_retryable_status(exc: Exception) -> bool:
    """Check if an HTTPStatusError is retryable (5xx)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


async def _request_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = _DEFAULT_RETRIES,
    backoff_base: float = _DEFAULT_BACKOFF,
    timeout: int = _DEFAULT_TIMEOUT,
    raw: bool = False,
    **kwargs,
):
    """Internal: execute an HTTP request with retry logic.

    Args:
        method: "GET" or "POST".
        url: The URL to request.
        max_retries: Number of retries (default 2 → 3 total attempts).
        backoff_base: Base delay for exponential backoff.
        timeout: Request timeout in seconds.
        raw: If True, return the httpx.Response instead of parsed JSON.
        **kwargs: Passed to httpx (params, json, headers, etc.).
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp if raw else resp.json()
        except _RETRYABLE as e:
            last_exc = e
        except httpx.HTTPStatusError as e:
            if _is_retryable_status(e) and attempt < max_retries:
                last_exc = e
            else:
                raise
        except Exception:
            raise  # Non-HTTP errors — don't retry

        if attempt < max_retries:
            delay = backoff_base * (2 ** attempt)
            logger.info("retry %d/%d %s %s after %.1fs: %s", attempt + 1, max_retries, method, url[:80], delay, last_exc)
            await asyncio.sleep(delay)

    raise last_exc


async def http_get(url: str, *, max_retries: int = _DEFAULT_RETRIES, timeout: int = _DEFAULT_TIMEOUT, raw: bool = False, **kwargs):
    """GET with retry. Returns parsed JSON by default, or httpx.Response if raw=True."""
    return await _request_with_retry("GET", url, max_retries=max_retries, timeout=timeout, raw=raw, **kwargs)


async def http_post(url: str, *, max_retries: int = _DEFAULT_RETRIES, timeout: int = _DEFAULT_TIMEOUT, raw: bool = False, **kwargs):
    """POST with retry. Returns parsed JSON by default, or httpx.Response if raw=True."""
    return await _request_with_retry("POST", url, max_retries=max_retries, timeout=timeout, raw=raw, **kwargs)


def with_retry(max_retries: int = 2, backoff_base: float = 1.0):
    """Decorator that retries an async function on transient HTTP errors.

    Retries on: connection errors, timeouts, 5xx status codes.
    Does NOT retry on: 4xx client errors, non-HTTP exceptions.

    Args:
        max_retries: Number of retry attempts (default 2, so 3 total attempts).
        backoff_base: Base delay in seconds for exponential backoff (1s, 2s, 4s...).
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except _RETRYABLE as e:
                    last_exc = e
                except httpx.HTTPStatusError as e:
                    if _is_retryable_status(e) and attempt < max_retries:
                        last_exc = e
                    else:
                        raise
                except Exception:
                    raise  # Non-HTTP errors — don't retry

                # Exponential backoff before next attempt
                if attempt < max_retries:
                    delay = backoff_base * (2 ** attempt)
                    logger.info(
                        "retry %d/%d for %s after %.1fs: %s",
                        attempt + 1, max_retries, fn.__name__, delay, last_exc,
                    )
                    await asyncio.sleep(delay)

            raise last_exc  # All retries exhausted
        return wrapper
    return decorator
