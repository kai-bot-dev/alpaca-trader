# alpaca-trader

Alpaca options paper trading system with CLI, FastAPI backend, and web dashboard.

## Setup

### Prerequisites
- Python 3.12+
- Alpaca paper trading account with API keys

### Installation

```bash
# Clone the repo
cd /Users/tonylesmb/claw-workspace/alpaca-trader

# Copy env template and fill in your keys
cp .env.example .env
# Edit .env with your ALPACA_API_KEY and ALPACA_SECRET_KEY

# Install in editable mode
pip install -e .
```

### Configuration

Edit `.env` with your Alpaca paper trading credentials:
```
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

## CLI Usage

```bash
# Account summary
alpaca-trader account

# Current positions with P&L
alpaca-trader positions

# Order history
alpaca-trader orders
alpaca-trader orders --status open

# Options chain lookup
alpaca-trader chain AAPL
alpaca-trader chain AAPL --expiry 2024-12-20 --type call
alpaca-trader chain AAPL --strike-min 150 --strike-max 200

# Place orders
alpaca-trader buy-call AAPL --expiry 2024-12-20 --strike 180 --qty 1
alpaca-trader buy-put AAPL --expiry 2024-12-20 --strike 170 --qty 1

# Cancel order
alpaca-trader cancel <ORDER_ID>

# Watchlist management
alpaca-trader watchlist list
alpaca-trader watchlist add AAPL
alpaca-trader watchlist rm AAPL

# JSON output (for programmatic use)
alpaca-trader account --json
alpaca-trader positions --json
```

## API Server

```bash
# Start the FastAPI server (port 8080)
uvicorn alpaca_trader.api.app:app --host 0.0.0.0 --port 8080 --reload

# API docs available at:
# http://localhost:8080/docs
```

## Project Structure

```
src/alpaca_trader/
  cli.py              # Typer CLI entry point
  api/
    app.py            # FastAPI application
    routes/
      account.py      # Account endpoints
      orders.py       # Order endpoints
      options.py      # Options chain endpoints
  core/
    client.py         # Alpaca API client wrapper
    models.py         # Pydantic models
    database.py       # SQLite database setup
```
