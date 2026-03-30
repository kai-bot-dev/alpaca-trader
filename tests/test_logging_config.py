"""Unit tests for core.logging_config module."""

import json
import logging
import sys

import pytest

from alpaca_trader.core.logging_config import JSONFormatter, HumanFormatter, setup_logging


class TestJSONFormatter:
    def test_basic_output_is_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger", level=logging.INFO, pathname="test.py",
            lineno=42, msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert parsed["logger"] == "test.logger"
        assert parsed["line"] == 42
        assert "timestamp" in parsed

    def test_extra_fields_included(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="order placed", args=(), exc_info=None,
        )
        record.symbol = "AAPL"
        record.qty = 10
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["extra"]["symbol"] == "AAPL"
        assert parsed["extra"]["qty"] == 10

    def test_exception_info_included(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="test.py",
            lineno=1, msg="failed", args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exc_info" in parsed
        assert "ValueError" in parsed["exc_info"]

    def test_no_extra_when_none_provided(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.DEBUG, pathname="test.py",
            lineno=1, msg="simple", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "extra" not in parsed

    def test_timestamp_is_utc_iso(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="ts", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        ts = parsed["timestamp"]
        assert "+00:00" in ts or "Z" in ts


class TestHumanFormatter:
    def test_output_contains_level_and_message(self):
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="test.mod", level=logging.WARNING, pathname="test.py",
            lineno=5, msg="something happened", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "WARNING" in output
        assert "something happened" in output
        assert "test.mod" in output

    def test_output_is_not_json(self):
        formatter = HumanFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hi", args=(), exc_info=None,
        )
        output = formatter.format(record)
        with pytest.raises(json.JSONDecodeError):
            json.loads(output)


class TestSetupLogging:
    def test_setup_json_format(self):
        setup_logging(level="DEBUG", format_type="json")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)
        assert root.level == logging.DEBUG

    def test_setup_text_format(self):
        setup_logging(level="WARNING", format_type="text")
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, HumanFormatter)
        assert root.level == logging.WARNING

    def test_setup_clears_existing_handlers(self):
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler())
        root.addHandler(logging.StreamHandler())
        assert len(root.handlers) >= 2
        setup_logging(format_type="text")
        assert len(root.handlers) == 1

    def test_noisy_loggers_suppressed(self):
        setup_logging(format_type="text")
        assert logging.getLogger("urllib3").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING

    def test_setup_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        monkeypatch.setenv("LOG_FORMAT", "json")
        setup_logging()
        root = logging.getLogger()
        assert root.level == logging.ERROR
        assert isinstance(root.handlers[0].formatter, JSONFormatter)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
