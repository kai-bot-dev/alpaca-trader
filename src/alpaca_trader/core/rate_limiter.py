"""Rate limiter and retry logic for Alpaca API calls."""

import asyncio
import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar, Optional

from requests.exceptions import RequestException

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class RateLimitError(Exception):
    """Raised when API rate limit is exceeded."""

    pass


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_backoff_ms: int = 100,
        max_backoff_ms: int = 10000,
        backoff_multiplier: float = 2.0,
    ):
        self.max_retries = max_retries
        self.initial_backoff_ms = initial_backoff_ms
        self.max_backoff_ms = max_backoff_ms
        self.backoff_multiplier = backoff_multiplier

    def get_backoff_ms(self, attempt: int) -> int:
        """Calculate exponential backoff in milliseconds."""
        backoff = self.initial_backoff_ms * (self.backoff_multiplier**attempt)
        return min(int(backoff), self.max_backoff_ms)


def with_rate_limit_retry(
    retry_config: Optional[RetryConfig] = None,
) -> Callable[[F], F]:
    """Decorator that adds rate limit handling and exponential backoff retry logic.

    Handles:
    - 429 (Too Many Requests) responses
    - 503 (Service Unavailable) responses
    - Network timeout/connection errors

    Args:
        retry_config: RetryConfig instance. If None, uses defaults.

    Returns:
        Decorated function with retry logic.

    Raises:
        RateLimitError: If rate limit is exceeded after all retries.
    """
    if retry_config is None:
        retry_config = RetryConfig()

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None

            for attempt in range(retry_config.max_retries):
                try:
                    return func(*args, **kwargs)
                except RequestException as e:
                    last_exception = e

                    # Check if this is a rate limit error (429)
                    if hasattr(e, "response") and e.response is not None:
                        status_code = e.response.status_code

                        if status_code == 429:
                            # Try to get Retry-After header
                            retry_after = e.response.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    wait_seconds = int(retry_after)
                                    logger.warning(
                                        f"Rate limited (429). Server requested {wait_seconds}s wait."
                                    )
                                    time.sleep(wait_seconds)
                                    continue
                                except (ValueError, TypeError):
                                    pass

                            # If no Retry-After, use exponential backoff
                            if attempt < retry_config.max_retries - 1:
                                backoff_ms = retry_config.get_backoff_ms(attempt)
                                logger.warning(
                                    f"Rate limited (429). Retrying in {backoff_ms}ms "
                                    f"(attempt {attempt + 1}/{retry_config.max_retries})"
                                )
                                time.sleep(backoff_ms / 1000)
                                continue
                            else:
                                raise RateLimitError(
                                    f"Rate limit exceeded after {retry_config.max_retries} retries"
                                ) from e

                        elif status_code == 503:
                            # Service unavailable - retry with backoff
                            if attempt < retry_config.max_retries - 1:
                                backoff_ms = retry_config.get_backoff_ms(attempt)
                                logger.warning(
                                    f"Service unavailable (503). Retrying in {backoff_ms}ms "
                                    f"(attempt {attempt + 1}/{retry_config.max_retries})"
                                )
                                time.sleep(backoff_ms / 1000)
                                continue

                    # Other errors - retry with backoff
                    if attempt < retry_config.max_retries - 1:
                        backoff_ms = retry_config.get_backoff_ms(attempt)
                        logger.warning(
                            f"Request failed: {e}. Retrying in {backoff_ms}ms "
                            f"(attempt {attempt + 1}/{retry_config.max_retries})"
                        )
                        time.sleep(backoff_ms / 1000)
                        continue

            # All retries exhausted
            if last_exception:
                raise last_exception
            raise RuntimeError("Unknown error in retry loop")

        return wrapper  # type: ignore

    return decorator


def with_async_rate_limit_retry(
    retry_config: Optional[RetryConfig] = None,
) -> Callable[[F], F]:
    """Async version of with_rate_limit_retry decorator.

    Works with async/await functions.

    Args:
        retry_config: RetryConfig instance. If None, uses defaults.

    Returns:
        Decorated async function with retry logic.
    """
    if retry_config is None:
        retry_config = RetryConfig()

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None

            for attempt in range(retry_config.max_retries):
                try:
                    return await func(*args, **kwargs)
                except RequestException as e:
                    last_exception = e

                    # Check if this is a rate limit error (429)
                    if hasattr(e, "response") and e.response is not None:
                        status_code = e.response.status_code

                        if status_code == 429:
                            # Try to get Retry-After header
                            retry_after = e.response.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    wait_seconds = int(retry_after)
                                    logger.warning(
                                        f"Rate limited (429). Server requested {wait_seconds}s wait."
                                    )
                                    await asyncio.sleep(wait_seconds)
                                    continue
                                except (ValueError, TypeError):
                                    pass

                            # If no Retry-After, use exponential backoff
                            if attempt < retry_config.max_retries - 1:
                                backoff_ms = retry_config.get_backoff_ms(attempt)
                                logger.warning(
                                    f"Rate limited (429). Retrying in {backoff_ms}ms "
                                    f"(attempt {attempt + 1}/{retry_config.max_retries})"
                                )
                                await asyncio.sleep(backoff_ms / 1000)
                                continue
                            else:
                                raise RateLimitError(
                                    f"Rate limit exceeded after {retry_config.max_retries} retries"
                                ) from e

                        elif status_code == 503:
                            # Service unavailable - retry with backoff
                            if attempt < retry_config.max_retries - 1:
                                backoff_ms = retry_config.get_backoff_ms(attempt)
                                logger.warning(
                                    f"Service unavailable (503). Retrying in {backoff_ms}ms "
                                    f"(attempt {attempt + 1}/{retry_config.max_retries})"
                                )
                                await asyncio.sleep(backoff_ms / 1000)
                                continue

                    # Other errors - retry with backoff
                    if attempt < retry_config.max_retries - 1:
                        backoff_ms = retry_config.get_backoff_ms(attempt)
                        logger.warning(
                            f"Request failed: {e}. Retrying in {backoff_ms}ms "
                            f"(attempt {attempt + 1}/{retry_config.max_retries})"
                        )
                        await asyncio.sleep(backoff_ms / 1000)
                        continue

            # All retries exhausted
            if last_exception:
                raise last_exception
            raise RuntimeError("Unknown error in retry loop")

        return wrapper  # type: ignore

    return decorator
