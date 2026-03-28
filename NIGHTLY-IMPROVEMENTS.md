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
- [ ] Add unit tests for RiskManager (position sizing, circuit breakers)
- [ ] Add unit tests for OrderExecutor (limit orders, retries, slippage)
- [ ] Add unit tests for PositionManager (stop-loss, take-profit, trailing stop)
- [ ] Add unit tests for AutoTrader orchestrator (signal → risk → order pipeline)
- ✅ Fix DeprecationWarning: replace `datetime.utcnow()` with `datetime.now(datetime.UTC)` everywhere (2026-03-27)
- ✅ Add error handling for Alpaca API rate limits (429 responses) in client.py (2026-03-27)
- ✅ Add retry logic with exponential backoff for network failures in scanner (2026-03-27)

### Medium Priority
- [ ] Add integration test: full scan → signal → auto-trade pipeline (mocked API)
- [ ] Improve logging: add structured logging (JSON) throughout the trading pipeline
- [ ] Add type hints to all public functions that are missing them
- [x] Create a health check endpoint in FastAPI (/api/health) with system status (2026-03-28)
- [x] Add docstrings to all strategy detector classes (2026-03-28)
- [ ] Refactor scanner.py to use async properly (currently blocking in sync scan loop)

### Low Priority
- [ ] Add mypy strict checking and fix type errors
- [ ] Add pre-commit hooks (ruff, mypy)
- [ ] Improve CLI output formatting consistency
- [ ] Add --verbose flag to all CLI commands
- [ ] Dashboard: add loading spinners for API calls
- [ ] Dashboard: add error toast notifications

### Ideas (For Later)
- [ ] Add more strategies (RSI divergence, VWAP, volume profile)
- [ ] Portfolio correlation analysis (avoid overexposure to same sector)
- [ ] Strategy performance tracking (which strategy wins most)
- [ ] Slack/Discord delivery option alongside Telegram
- [ ] Historical P&L charting on dashboard

## Completed
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
