"""Unit tests for rate_limiter module."""

import pytest
from unittest.mock import Mock, patch
from requests.exceptions import RequestException, ConnectionError

from alpaca_trader.core.rate_limiter import (
    with_rate_limit_retry,
    RetryConfig,
    RateLimitError,
)


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_config(self):
        """Test RetryConfig with default values."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.initial_backoff_ms == 100
        assert config.max_backoff_ms == 10000
        assert config.backoff_multiplier == 2.0

    def test_custom_config(self):
        """Test RetryConfig with custom values."""
        config = RetryConfig(
            max_retries=5,
            initial_backoff_ms=200,
            max_backoff_ms=5000,
            backoff_multiplier=3.0,
        )
        assert config.max_retries == 5
        assert config.initial_backoff_ms == 200
        assert config.max_backoff_ms == 5000
        assert config.backoff_multiplier == 3.0

    def test_exponential_backoff(self):
        """Test exponential backoff calculation."""
        config = RetryConfig(initial_backoff_ms=100, backoff_multiplier=2.0)

        assert config.get_backoff_ms(0) == 100
        assert config.get_backoff_ms(1) == 200
        assert config.get_backoff_ms(2) == 400
        assert config.get_backoff_ms(3) == 800

    def test_max_backoff_capped(self):
        """Test that backoff is capped at max_backoff_ms."""
        config = RetryConfig(
            initial_backoff_ms=100,
            max_backoff_ms=500,
            backoff_multiplier=2.0,
        )

        assert config.get_backoff_ms(0) == 100
        assert config.get_backoff_ms(1) == 200
        assert config.get_backoff_ms(2) == 400
        assert config.get_backoff_ms(3) == 500  # capped
        assert config.get_backoff_ms(10) == 500  # still capped


class TestWithRateLimitRetry:
    """Tests for with_rate_limit_retry decorator."""

    def test_successful_call_no_retry(self):
        """Test that successful calls don't trigger retries."""
        call_count = 0

        @with_rate_limit_retry(RetryConfig(max_retries=3))
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_rate_limit_429_with_retry_after_header(self):
        """Test handling of 429 with Retry-After header."""
        call_count = 0

        @with_rate_limit_retry(RetryConfig(max_retries=3, initial_backoff_ms=10))
        def rate_limited_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                response = Mock()
                response.status_code = 429
                response.headers = {"Retry-After": "0"}  # 0 seconds for testing
                error = RequestException()
                error.response = response
                raise error
            return "success"

        with patch("alpaca_trader.core.rate_limiter.time.sleep"):
            result = rate_limited_once()
            assert result == "success"
            assert call_count == 2

    def test_rate_limit_429_exceeds_max_retries(self):
        """Test that RateLimitError is raised after max retries."""

        @with_rate_limit_retry(RetryConfig(max_retries=2))
        def always_rate_limited():
            response = Mock()
            response.status_code = 429
            response.headers = {}
            error = RequestException()
            error.response = response
            raise error

        with patch("alpaca_trader.core.rate_limiter.time.sleep"):
            with pytest.raises(RateLimitError):
                always_rate_limited()

    def test_service_unavailable_503_retries(self):
        """Test handling of 503 Service Unavailable."""
        call_count = 0

        @with_rate_limit_retry(RetryConfig(max_retries=3, initial_backoff_ms=10))
        def service_unavailable_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                response = Mock()
                response.status_code = 503
                response.headers = {}
                error = RequestException()
                error.response = response
                raise error
            return "success"

        with patch("alpaca_trader.core.rate_limiter.time.sleep"):
            result = service_unavailable_once()
            assert result == "success"
            assert call_count == 2

    def test_connection_error_retries(self):
        """Test handling of connection errors."""
        call_count = 0

        @with_rate_limit_retry(RetryConfig(max_retries=3, initial_backoff_ms=10))
        def connection_error_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Network timeout")
            return "success"

        with patch("alpaca_trader.core.rate_limiter.time.sleep"):
            result = connection_error_once()
            assert result == "success"
            assert call_count == 2

    def test_multiple_retries_before_success(self):
        """Test that function is retried multiple times before success."""
        call_count = 0

        @with_rate_limit_retry(RetryConfig(max_retries=5, initial_backoff_ms=10))
        def fails_twice_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                response = Mock()
                response.status_code = 503
                response.headers = {}
                error = RequestException()
                error.response = response
                raise error
            return "success"

        with patch("alpaca_trader.core.rate_limiter.time.sleep"):
            result = fails_twice_then_succeeds()
            assert result == "success"
            assert call_count == 3

    def test_default_retry_config(self):
        """Test that decorator works with default RetryConfig."""
        call_count = 0

        @with_rate_limit_retry()  # No config passed
        def func_with_default_config():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                response = Mock()
                response.status_code = 503
                response.headers = {}
                error = RequestException()
                error.response = response
                raise error
            return "success"

        with patch("alpaca_trader.core.rate_limiter.time.sleep"):
            result = func_with_default_config()
            assert result == "success"
            assert call_count == 2

    def test_preserves_function_metadata(self):
        """Test that decorator preserves function name and docstring."""

        @with_rate_limit_retry()
        def my_function():
            """My function docstring."""
            return "test"

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My function docstring."


class TestRateLimitError:
    """Tests for RateLimitError exception."""

    def test_rate_limit_error_is_exception(self):
        """Test that RateLimitError is an Exception."""
        error = RateLimitError("Test error")
        assert isinstance(error, Exception)

    def test_rate_limit_error_message(self):
        """Test that RateLimitError preserves message."""
        message = "Custom error message"
        error = RateLimitError(message)
        assert str(error) == message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
