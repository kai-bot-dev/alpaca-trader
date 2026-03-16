# PRD: Alpaca Options Paper Trading System

## Context
Tony wants to paper trade options on Alpaca using Bollinger Band-based strategies. OpenClaw (his AI assistant running on Mac mini) will serve as the orchestrator — dispatching Claude Code as the coding agent to build the system, monitoring positions, and sending alerts via Telegram. The system needs a CLI backend for OpenClaw to interact with programmatically, plus a polished web dashboard for Tony to visually monitor positions, P&L, and options chains.

Alpaca paper trading API keys are already set up in a `.env` file (not committed to git).

## Product Overview
- **Name:** alpaca-trader
- **Location:** /Users/tonylesmb/claw-workspace/alpaca-trader/
- **Stack:** Python (FastAPI backend), React + Tailwind/shadcn (frontend), SQLite (local state)
- **Architecture:** Monorepo with CLI + API server + web dashboard

## System Architecture
```
Tony (Browser) ──→ Web Dashboard (React)
                          │
OpenClaw (Telegram) ──→ CLI ──→ FastAPI Backend ──→ Alpaca API
                          │              │
                     Claude Code      SQLite DB
                   (builds/maintains) (state, history, alerts)
```

## Core Features

### Phase 1: Backend + CLI (MVP)

#### 1.1 Account Management
- View account info (buying power, equity, cash)
- View current positions with real-time P&L
- View order history (filled, pending, cancelled)

#### 1.2 Options Chain Lookup
- Query options chains by ticker symbol
- Filter by expiry date, strike price, option type (call/put)
- Display Greeks (delta, gamma, theta, vega, IV)
- Show bid/ask spread, volume, open interest

#### 1.3 Order Management
- Place single-leg orders: buy/sell calls and puts
- Place multi-leg orders: vertical spreads, iron condors, straddles/strangles
- Cancel and modify open orders
- Order validation before submission (buying power check, contract verification)

#### 1.4 Bollinger Band Strategy Engine

Three core strategies, each producing actionable signals:

**The Squeeze (Breakout)**
- Monitor Bollinger Band width (BBW) for contraction below configurable threshold
- Alert when squeeze is detected on watched tickers
- Signal: candle close outside band after squeeze + volume confirmation
- Auto-suggest entry, stop-loss (opposite band), and target

**The Bollinger Bounce (Mean Reversion)**
- Detect price touching/crossing lower or upper band in range-bound markets
- Confirm range-bound via ADX < 25 or similar filter
- Signal: buy at lower band, sell at middle/upper band (and inverse)
- RSI confirmation (oversold at lower band, overbought at upper)

**Walking the Bands (Trend Following)**
- Detect sustained price action along an outer band
- Confirm trend strength with MACD or ADX > 25
- Signal: enter in trend direction, exit on middle band cross
- Trail stop along middle band

**Shared Strategy Infrastructure:**
- Configurable parameters (period, std dev, confirmation indicators)
- Backtesting against historical data before live paper trading
- Signal logging with timestamps and outcomes for strategy refinement
- Default settings: 20-period SMA, 2.0 standard deviation

#### 1.5 CLI Interface

Commands OpenClaw will use:
```
alpaca-trader account          # Account summary
alpaca-trader positions        # Current positions + P&L
alpaca-trader orders [--status] # Order history
alpaca-trader chain TICKER     # Options chain
alpaca-trader buy-call TICKER ... # Place call order
alpaca-trader buy-put TICKER ...  # Place put order
alpaca-trader spread TICKER ...   # Place spread order
alpaca-trader cancel ORDER_ID  # Cancel order
alpaca-trader scan [--strategy] # Run Bollinger scan on watchlist
alpaca-trader watchlist [add|rm] # Manage watchlist
alpaca-trader alerts           # View active alerts
alpaca-trader backtest TICKER ... # Backtest a strategy
```

All commands output JSON (for OpenClaw parsing) with `--json` flag, human-readable by default.

### Phase 2: Web Dashboard

#### 2.1 Design
- Style: Modern dark-mode-first, Tailwind CSS + shadcn/ui components
- Responsive: Works on desktop and mobile
- Charts: lightweight-charts (TradingView) for price + Bollinger Bands overlay

#### 2.2 Dashboard Pages
- **Overview / Home:** Portfolio summary, active positions, recent orders, active Bollinger signals
- **Options Chain Explorer:** Ticker search, chain grid, Greeks, one-click order
- **Positions & P&L:** Detailed breakdown, P&L chart over time, per-strategy performance
- **Strategy Monitor:** Live Bollinger Band status, squeeze indicator, active signals
- **Order Management:** Place/cancel/view orders
- **Settings:** Watchlist, strategy params, alert preferences

#### 2.3 Real-time Updates
- WebSocket connection to backend for live position/order updates
- Auto-refresh options data at configurable intervals

### Phase 3: Monitoring & Alerts (via OpenClaw + Telegram)

#### 3.1 Alert Types
- Order fills: Notify on partial and full fills
- P&L thresholds: Alert when position or portfolio P&L crosses user-defined levels
- Expiry warnings: Alert at 7 days, 3 days, 1 day, and day-of expiry
- Bollinger signals: Push squeeze detections, bounce signals, band walk entries
- Price targets: Alert when underlying hits user-set price levels

#### 3.2 Alert Delivery
- Backend exposes `/alerts` webhook endpoint
- OpenClaw polls or subscribes to alert feed
- Delivers formatted alerts to Tony via Telegram

#### 3.3 Scheduled Scans
- Cron job via OpenClaw cron system runs Bollinger scans on watchlist
- Default: every 15 minutes during market hours
- Summary report at market open and close

## Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.12+ | alpaca-py SDK, rich data science ecosystem for TA |
| API Framework | FastAPI | Async, WebSocket support, auto-docs |
| Frontend | React + Vite + Tailwind + shadcn/ui | Modern, polished, fast to build |
| Database | SQLite | Local-only, zero config, sufficient for paper trading |
| TA Library | pandas-ta | Bollinger Bands, RSI, MACD, ADX calculations |
| Charts | lightweight-charts (TradingView) | Professional-grade financial charts |
| Process Manager | PM2 or systemd | Keep backend running on Mac mini |

## Build Order

### Sprint 1: Foundation (Phase 1 MVP)
- Project scaffolding: Python package, FastAPI app, CLI entry point
- Alpaca API client wrapper (account, positions, orders)
- Options chain data fetching and formatting
- Order placement and management (single-leg)
- CLI commands with JSON output
- SQLite schema for watchlist, order history, alert config

### Sprint 2: Strategy Engine
- Bollinger Band calculation engine (with configurable params)
- Historical data fetching for backtesting
- Squeeze detection algorithm
- Bounce detection algorithm
- Band walk detection algorithm
- Scan command: run strategies across watchlist
- Backtest command with results summary

### Sprint 3: Multi-leg & Advanced Orders
- Spread order support (verticals, iron condors, straddles)
- Order modification support
- Position-level P&L tracking

### Sprint 4: Web Dashboard
- React + Vite project setup with Tailwind + shadcn
- All dashboard pages (Overview, Chain, Positions, Strategy, Orders, Settings)
- WebSocket integration for real-time updates

### Sprint 5: Alerts & Monitoring
- Alert engine in backend (event detection + queueing)
- Alert API endpoint for OpenClaw consumption
- OpenClaw skill for interacting with alpaca-trader
- Telegram alert formatting and delivery
- Cron job setup for scheduled scans

## Files to Create

```
alpaca-trader/
  pyproject.toml
  README.md
  .env.example          # Template (real .env never committed)
  .gitignore
  src/
    alpaca_trader/
      __init__.py
      cli.py            # CLI entry point (typer)
      api/
        app.py          # FastAPI application
        routes/
          account.py
          orders.py
          options.py
          strategies.py
          alerts.py
          websocket.py  # WebSocket handler
      core/
        client.py       # Alpaca API client wrapper
        models.py       # Pydantic models
        database.py     # SQLite setup
      strategies/
        bollinger.py    # BB calculations
        squeeze.py      # Squeeze detection
        bounce.py       # Mean reversion
        trend.py        # Band walking
        scanner.py      # Watchlist scanner
        backtest.py     # Backtesting engine
      alerts/
        engine.py       # Alert detection + queue
        types.py        # Alert type definitions
  frontend/
    package.json
    src/
      App.tsx
      pages/
        Overview.tsx
        OptionsChain.tsx
        Positions.tsx
        StrategyMonitor.tsx
        Orders.tsx
        Settings.tsx
      components/
        ...
  tests/
    ...
```

## Security
- API keys stored in `.env` file only (never committed, never read by AI)
- `.env` is gitignored
- Code references env vars by name only: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL`
