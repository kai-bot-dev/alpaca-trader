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
- [ ] Fix DeprecationWarning: replace `datetime.utcnow()` with `datetime.now(datetime.UTC)` everywhere
- [ ] Add error handling for Alpaca API rate limits (429 responses) in client.py
- [ ] Add retry logic with exponential backoff for network failures in scanner

### Medium Priority
- [ ] Add integration test: full scan → signal → auto-trade pipeline (mocked API)
- [ ] Improve logging: add structured logging (JSON) throughout the trading pipeline
- [ ] Add type hints to all public functions that are missing them
- [ ] Create a health check endpoint in FastAPI (/api/health) with system status
- [ ] Add docstrings to all strategy detector classes
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
*(Items move here after completion)*
