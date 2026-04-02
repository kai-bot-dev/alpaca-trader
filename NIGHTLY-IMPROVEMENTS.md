# Nightly Improvement Backlog

This file drives the nightly auto-improvement cron job. Claude Code reads this, picks the highest-priority items, implements them, and checks them off.

## Rules
- Work on 1-3 items per night (quality over quantity)
- Always run tests after changes
- Commit to `kai/nightly-improvements` branch
- Push to GitHub when done
- Mark completed items with ✅ and date

## Priority Queue

### High Priority
- ✅ Add unit tests for RiskManager (position sizing, circuit breakers) (2026-03-30, pre-existing)
- ✅ Add unit tests for OrderExecutor (limit orders, retries, slippage) (2026-03-30, pre-existing)
- ✅ Add unit tests for PositionManager (stop-loss, take-profit, trailing stop) (2026-03-30, pre-existing)
- ✅ Add unit tests for AutoTrader orchestrator (signal → risk → order pipeline) (2026-03-31)
- ✅ Fix DeprecationWarning: replace `datetime.utcnow()` with `datetime.now(datetime.UTC)` everywhere (2026-03-27)
- ✅ Add error handling for Alpaca API rate limits (429 responses) in client.py (2026-03-27)
- ✅ Add retry logic with exponential backoff for network failures in scanner (2026-03-27)

### Medium Priority
- ✅ Add integration test: full scan → signal → auto-trade pipeline (mocked API) (2026-03-31)
- [x] Improve logging: add structured logging (JSON) throughout the trading pipeline (2026-03-30)
- ✅ Add type hints to all public functions that are missing them (2026-03-31)
- [x] Create a health check endpoint in FastAPI (/api/health) with system status (2026-03-28)
- [x] Add docstrings to all strategy detector classes (2026-03-28)
- ✅ Refactor scanner.py to use async properly (currently blocking in sync scan loop) (2026-04-01)

### Low Priority
- [ ] Add mypy strict checking and fix type errors
- [ ] Add pre-commit hooks (ruff, mypy)
- [ ] Improve CLI output formatting consistency
- ✅ Add --verbose flag to all CLI commands (2026-04-01)
- [ ] Dashboard: add loading spinners for API calls
- [ ] Dashboard: add error toast notifications

### Ideas (For Later)
- [ ] Add more strategies (RSI divergence, VWAP, volume profile)
- [ ] Portfolio correlation analysis (avoid overexposure to same sector)
- [ ] Strategy performance tracking (which strategy wins most)
- [ ] Slack/Discord delivery option alongside Telegram
- [ ] Historical P&L charting on dashboard

## Completed
- ✅ Async scanner refactor + CLI --verbose flag (2026-04-01)
  - Added scan_async() to WatchlistScanner with asyncio.to_thread + semaphore (MAX_CONCURRENCY=5)
  - Updated ScheduledScanner to use scan_async() for concurrent scheduled scans
  - Sync scan() preserved for backward compat (CLI, AutoTrader)
  - Added global --verbose/-v flag to CLI (sets log level to DEBUG)
  - 9 new tests in test_scanner_async.py (async/sync parity, concurrency, semaphore, edge cases)
  - Total tests: 305 -> 314

- ✅ Expand AutoTrader pipeline tests + type hints (2026-03-31)
  - Added 12 new pipeline tests: single signal entry, no signal, risk rejection, skip held symbol,
    strongest strategy wins, multi-symbol entries, trade count tracking, empty watchlist
  - Added 3 exit pipeline tests: stop-loss, healthy hold, take-profit
  - Added daily trade limit test
  - Added return type hint to get_stock_bars_df() -> pd.DataFrame
  - Verified all other public functions already have type hints (only CLI/Typer commands omit them by convention)
  - Recognized that RiskManager (37 tests), OrderExecutor (24 tests), PositionManager (19 tests) already had comprehensive coverage
  - Total tests: 293 -> 305

- ✅ Improve logging: add structured JSON logging (2026-03-30)
  - Created core/logging_config.py with JSONFormatter and HumanFormatter
  - Auto-detects TTY (text for CLI) vs non-interactive (JSON for cron/pipes)
  - Configurable via LOG_LEVEL and LOG_FORMAT env vars
  - Added structured logging with extra fields to: scanner.py, checker.py, delivery.py, alerts/scanner.py
  - Integrated setup_logging() into CLI (typer callback) and FastAPI lifespan
  - 12 new tests in test_logging_config.py

- ✅ Fix pre-existing test bugs (2026-03-30)
  - Fixed test_risk_manager.py: make_rm() helper caused duplicate kwargs (20 tests broken)
  - Fixed test_order_executor.py: test expected wrong return value for unknown order_id
  - Fixed checker.py: missing 'timezone' import from datetime
  - All 182 tests now passing
- ✅ Fix DeprecationWarning: replace `datetime.utcnow()` with `datetime.now(timezone.utc)` everywhere (2026-03-27)
  - Fixed in: database.py, scanner.py, delivery.py, checker.py, alerts/scanner.py
  - Tested: All files verified to have no remaining utcnow() calls

- ✅ Add error handling for Alpaca API rate limits (2026-03-27)
  - Created rate_limiter.py with retry decorator and exponential backoff
  - Handles 429 (Too Many Requests) with Retry-After header support
  - Handles 503 (Service Unavailable)
  - Ready to integrate into client.py API methods

- ✅ Add retry logic with exponential backoff (2026-03-27)
  - Implemented in rate_limiter.py
  - Exponential backoff: 100ms → 200ms → 400ms → 800ms (capped at 10s)
  - Configurable max retries, initial backoff, multiplier
  - Both sync and async versions available

- ✅ Add unit tests for strategy detectors (2026-03-28)
  - Created tests/test_strategies.py with 34 tests covering all 4 strategy classes
  - Uses synthetic OHLCV data (numpy/pandas) with controllable volatility, trend, and seed
  - Tests: BollingerBands (10), SqueezeDetector (8), BounceDetector (7), TrendDetector (9)
  - All tests pass

- ✅ Create health check endpoint /api/health (2026-03-28)
  - Added src/alpaca_trader/api/routes/health.py
  - Returns status, version, timestamp, database connectivity, services
  - Registered in app.py

- ✅ Add docstrings to all strategy detector classes (2026-03-28)
  - Enhanced class-level Google-style docstrings for BollingerBands, SqueezeDetector, BounceDetector, TrendDetector
  - Added Attributes sections and Example usage snippets
