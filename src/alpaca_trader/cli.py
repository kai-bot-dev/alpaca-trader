"""CLI entry point for alpaca-trader using Typer."""

import asyncio
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from alpaca_trader.core.logging_config import setup_logging
from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.backtest import Backtester
from alpaca_trader.alerts.checker import AlertChecker
from alpaca_trader.alerts.delivery import TelegramDeliveryQueue
from alpaca_trader.alerts.formatter import format_alert_telegram
from alpaca_trader.alerts.scanner import ScheduledScanner

app = typer.Typer(
    name="alpaca-trader",
    help="Alpaca options paper trading CLI",
    add_completion=False,
)


@app.callback()
def main_callback() -> None:
    """Initialize logging on CLI startup."""
    setup_logging()

console = Console()


def _json_serializer(obj):
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def _print_json(data):
    """Print data as formatted JSON."""
    typer.echo(json.dumps(data, default=_json_serializer, indent=2))


def _fmt_decimal(value, prefix="$", color="white") -> str:
    """Format a decimal value with color for positive/negative."""
    if value is None:
        return "—"
    try:
        v = float(value)
        formatted = f"{prefix}{v:,.2f}"
        if v > 0:
            return f"[green]{formatted}[/green]"
        elif v < 0:
            return f"[red]{formatted}[/red]"
        return formatted
    except (TypeError, ValueError):
        return str(value)


def _fmt_pct(value) -> str:
    """Format a percentage value."""
    if value is None:
        return "—"
    try:
        v = float(value) * 100
        formatted = f"{v:+.2f}%"
        if v > 0:
            return f"[green]{formatted}[/green]"
        elif v < 0:
            return f"[red]{formatted}[/red]"
        return formatted
    except (TypeError, ValueError):
        return str(value)


# --- account command ---

@app.command()
def account(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show account summary (buying power, equity, cash)."""
    try:
        data = alpaca.get_account()
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]API error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(data)
        return

    table = Table(title="Account Summary", show_header=False, box=None)
    table.add_column("Field", style="dim", width=24)
    table.add_column("Value")

    table.add_row("Account Number", str(data.get("account_number", "—")))
    table.add_row("Status", str(data.get("status", "—")))
    table.add_row("Currency", str(data.get("currency", "USD")))
    table.add_row("Portfolio Value", _fmt_decimal(data.get("portfolio_value")))
    table.add_row("Equity", _fmt_decimal(data.get("equity")))
    table.add_row("Cash", _fmt_decimal(data.get("cash")))
    table.add_row("Buying Power", _fmt_decimal(data.get("buying_power")))
    table.add_row("Regt Buying Power", _fmt_decimal(data.get("regt_buying_power")))
    table.add_row("Day Trade Count", str(data.get("day_trade_count", 0)))
    table.add_row("Pattern Day Trader", str(data.get("pattern_day_trader", False)))

    console.print(table)


# --- positions command ---

@app.command()
def positions(
    history: bool = typer.Option(False, "--history", help="Show P&L history over time per position"),
    summary: bool = typer.Option(False, "--summary", help="Show portfolio-level P&L summary"),
    days: int = typer.Option(30, "--days", help="Days of history to show (with --history)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show current open positions with P&L."""
    asyncio.run(db.init_db())

    if summary:
        summary_data = asyncio.run(db.get_portfolio_pnl_summary())
        if json_output:
            _print_json(summary_data)
            return

        panel_lines = [
            f"Positions: {summary_data['position_count']}  |  Winners: [green]{summary_data['winners']}[/green]  Losers: [red]{summary_data['losers']}[/red]  Win Rate: {summary_data['win_rate']*100:.1f}%"
        ]
        console.print(Panel("\n".join(panel_lines), title="Portfolio P&L Summary"))

        t = Table(show_header=False, box=None)
        t.add_column("Metric", style="dim", width=24)
        t.add_column("Value")
        t.add_row("Total Unrealized P&L", _fmt_decimal(summary_data["total_unrealized_pnl"]))
        t.add_row("Total Realized P&L", _fmt_decimal(summary_data["total_realized_pnl"]))
        t.add_row("Total P&L", _fmt_decimal(summary_data["total_pnl"]))
        console.print(t)
        return

    if history:
        try:
            positions_data = alpaca.get_positions()
        except EnvironmentError as e:
            console.print(f"[red]Configuration error:[/red] {e}")
            raise typer.Exit(1)
        except Exception as e:
            console.print(f"[red]API error:[/red] {e}")
            raise typer.Exit(1)

        symbols = [p.get("symbol") for p in positions_data if p.get("symbol")]
        all_history = {}
        for sym in symbols:
            snaps = asyncio.run(db.get_pnl_history(sym, days=days))
            all_history[sym] = snaps

        if json_output:
            _print_json(all_history)
            return

        for sym, snaps in all_history.items():
            if not snaps:
                console.print(f"[dim]{sym}: no history (run 'positions --snapshot' to record)[/dim]")
                continue
            table = Table(title=f"{sym} — P&L History ({days}d)")
            table.add_column("Timestamp", style="dim")
            table.add_column("Qty", justify="right")
            table.add_column("Avg Entry", justify="right")
            table.add_column("Price", justify="right")
            table.add_column("Unrealized P&L", justify="right")
            for snap in snaps:
                table.add_row(
                    str(snap.get("timestamp", "—"))[:19],
                    str(snap.get("qty", "—")),
                    _fmt_decimal(snap.get("avg_entry")),
                    _fmt_decimal(snap.get("current_price")),
                    _fmt_decimal(snap.get("unrealized_pnl")),
                )
            console.print(table)
        return

    try:
        data = alpaca.get_positions()
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]API error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(data)
        return

    if not data:
        console.print("[dim]No open positions.[/dim]")
        return

    table = Table(title=f"Open Positions ({len(data)})")
    table.add_column("Symbol", style="bold cyan")
    table.add_column("Qty", justify="right")
    table.add_column("Avg Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Market Value", justify="right")
    table.add_column("Unrealized P&L", justify="right")
    table.add_column("P&L %", justify="right")

    for p in data:
        table.add_row(
            p.get("symbol", "—"),
            str(p.get("qty", "—")),
            _fmt_decimal(p.get("avg_entry_price")),
            _fmt_decimal(p.get("current_price")),
            _fmt_decimal(p.get("market_value")),
            _fmt_decimal(p.get("unrealized_pl")),
            _fmt_pct(p.get("unrealized_plpc")),
        )

    console.print(table)


# --- orders command ---

@app.command()
def orders(
    status: Optional[str] = typer.Option(None, "--status", help="Filter: open, closed, all"),
    limit: int = typer.Option(20, "--limit", help="Max number of orders to show"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show order history."""
    try:
        data = alpaca.get_orders(status=status, limit=limit)
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]API error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(data)
        return

    if not data:
        console.print("[dim]No orders found.[/dim]")
        return

    table = Table(title=f"Orders ({len(data)})")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Symbol", style="bold cyan")
    table.add_column("Side")
    table.add_column("Type")
    table.add_column("Qty", justify="right")
    table.add_column("Filled", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Status")
    table.add_column("Submitted")

    for o in data:
        order_id = str(o.get("id", ""))[:8] + "..."
        side = o.get("side", "—")
        side_styled = f"[green]{side}[/green]" if side == "buy" else f"[red]{side}[/red]"
        status_val = str(o.get("status", "—"))
        submitted = str(o.get("submitted_at", "—"))[:19]

        table.add_row(
            order_id,
            o.get("symbol", "—"),
            side_styled,
            o.get("order_type") or o.get("type", "—"),
            str(o.get("qty", "—")),
            str(o.get("filled_qty", "—")),
            _fmt_decimal(o.get("filled_avg_price") or o.get("limit_price")),
            status_val,
            submitted,
        )

    console.print(table)


# --- chain command ---

@app.command()
def chain(
    ticker: str = typer.Argument(..., help="Underlying ticker symbol (e.g. AAPL)"),
    expiry: Optional[str] = typer.Option(None, "--expiry", help="Expiration date (YYYY-MM-DD)"),
    option_type: Optional[str] = typer.Option(None, "--type", help="call or put"),
    strike_min: Optional[float] = typer.Option(None, "--strike-min", help="Min strike price"),
    strike_max: Optional[float] = typer.Option(None, "--strike-max", help="Max strike price"),
    limit: int = typer.Option(50, "--limit", help="Max contracts to fetch"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Look up options chain for a ticker."""
    expiry_date = None
    if expiry:
        try:
            expiry_date = date.fromisoformat(expiry)
        except ValueError:
            console.print(f"[red]Invalid date format:[/red] {expiry} (use YYYY-MM-DD)")
            raise typer.Exit(1)

    try:
        contracts = alpaca.get_option_chain(
            underlying_symbol=ticker.upper(),
            expiration_date=expiry_date,
            option_type=option_type,
            strike_price_gte=strike_min,
            strike_price_lte=strike_max,
            limit=limit,
        )
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]API error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(contracts)
        return

    if not contracts:
        console.print(f"[dim]No options contracts found for {ticker.upper()}.[/dim]")
        return

    table = Table(title=f"Options Chain: {ticker.upper()} ({len(contracts)} contracts)")
    table.add_column("Symbol", style="cyan", width=22)
    table.add_column("Type")
    table.add_column("Expiry")
    table.add_column("Strike", justify="right")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Last", justify="right")
    table.add_column("IV", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("OI", justify="right")

    for c in contracts:
        greeks = c.get("greeks") or {}
        opt_type = c.get("type") or c.get("option_type") or "—"
        type_styled = f"[green]{opt_type}[/green]" if opt_type == "call" else f"[red]{opt_type}[/red]"
        iv = greeks.get("implied_volatility") or c.get("implied_volatility")
        iv_str = f"{float(iv)*100:.1f}%" if iv else "—"
        delta = greeks.get("delta")
        delta_str = f"{float(delta):.3f}" if delta else "—"

        table.add_row(
            c.get("symbol", "—"),
            type_styled,
            str(c.get("expiration_date", "—")),
            _fmt_decimal(c.get("strike_price")),
            _fmt_decimal(c.get("bid_price")),
            _fmt_decimal(c.get("ask_price")),
            _fmt_decimal(c.get("last_price") or c.get("close_price")),
            iv_str,
            delta_str,
            str(c.get("open_interest") or "—"),
        )

    console.print(table)


# --- buy-call command ---

@app.command(name="buy-call")
def buy_call(
    ticker: str = typer.Argument(..., help="Underlying ticker symbol"),
    expiry: str = typer.Option(..., "--expiry", help="Expiration date (YYYY-MM-DD)"),
    strike: float = typer.Option(..., "--strike", help="Strike price"),
    qty: int = typer.Option(1, "--qty", help="Number of contracts"),
    limit_price: Optional[float] = typer.Option(None, "--limit", help="Limit price (market order if omitted)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Buy a call option."""
    try:
        expiry_date = date.fromisoformat(expiry)
    except ValueError:
        console.print(f"[red]Invalid date format:[/red] {expiry} (use YYYY-MM-DD)")
        raise typer.Exit(1)

    symbol = alpaca.build_option_symbol(ticker, expiry_date, "call", strike)
    console.print(f"Placing buy order for [cyan]{symbol}[/cyan] x{qty}...")

    try:
        if limit_price:
            order = alpaca.place_limit_order(symbol, qty, "buy", limit_price)
        else:
            order = alpaca.place_market_order(symbol, qty, "buy")
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Order failed:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(order)
        return

    console.print(f"[green]Order placed:[/green] {order.get('id', '—')}")
    console.print(f"  Status: {order.get('status', '—')}")
    console.print(f"  Symbol: {order.get('symbol', symbol)}")


# --- buy-put command ---

@app.command(name="buy-put")
def buy_put(
    ticker: str = typer.Argument(..., help="Underlying ticker symbol"),
    expiry: str = typer.Option(..., "--expiry", help="Expiration date (YYYY-MM-DD)"),
    strike: float = typer.Option(..., "--strike", help="Strike price"),
    qty: int = typer.Option(1, "--qty", help="Number of contracts"),
    limit_price: Optional[float] = typer.Option(None, "--limit", help="Limit price (market order if omitted)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Buy a put option."""
    try:
        expiry_date = date.fromisoformat(expiry)
    except ValueError:
        console.print(f"[red]Invalid date format:[/red] {expiry} (use YYYY-MM-DD)")
        raise typer.Exit(1)

    symbol = alpaca.build_option_symbol(ticker, expiry_date, "put", strike)
    console.print(f"Placing buy order for [cyan]{symbol}[/cyan] x{qty}...")

    try:
        if limit_price:
            order = alpaca.place_limit_order(symbol, qty, "buy", limit_price)
        else:
            order = alpaca.place_market_order(symbol, qty, "buy")
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Order failed:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(order)
        return

    console.print(f"[green]Order placed:[/green] {order.get('id', '—')}")
    console.print(f"  Status: {order.get('status', '—')}")
    console.print(f"  Symbol: {order.get('symbol', symbol)}")


# --- spread command ---

@app.command()
def spread(
    ticker: str = typer.Argument(..., help="Underlying ticker symbol (e.g. AAPL)"),
    spread_type: str = typer.Option(..., "--type", help="Spread type: vertical, condor, straddle, strangle"),
    expiry: str = typer.Option(..., "--expiry", help="Expiration date (YYYY-MM-DD)"),
    strike: float = typer.Option(None, "--strike", help="Strike price (required for vertical/straddle/strangle)"),
    width: Optional[float] = typer.Option(None, "--width", help="Strike width in points (vertical/condor/strangle)"),
    qty: int = typer.Option(1, "--qty", help="Number of contracts"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Place a multi-leg spread order (vertical, condor, straddle, strangle)."""
    valid_types = ("vertical", "condor", "straddle", "strangle")
    if spread_type not in valid_types:
        console.print(f"[red]Invalid spread type.[/red] Choose from: {', '.join(valid_types)}")
        raise typer.Exit(1)

    try:
        expiry_date = date.fromisoformat(expiry)
    except ValueError:
        console.print(f"[red]Invalid date format:[/red] {expiry} (use YYYY-MM-DD)")
        raise typer.Exit(1)

    try:
        if spread_type == "straddle":
            if strike is None:
                console.print("[red]--strike is required for straddle[/red]")
                raise typer.Exit(1)
            console.print(f"Placing [cyan]straddle[/cyan] on {ticker.upper()} {expiry} @{strike} x{qty}...")
            order = alpaca.place_straddle(ticker.upper(), expiry_date, strike, qty=qty)

        elif spread_type == "strangle":
            if strike is None or width is None:
                console.print("[red]--strike (call strike) and --width (put strike distance) are required for strangle[/red]")
                raise typer.Exit(1)
            call_strike = strike
            put_strike = strike - width
            console.print(f"Placing [cyan]strangle[/cyan] on {ticker.upper()} {expiry} call@{call_strike} put@{put_strike} x{qty}...")
            order = alpaca.place_strangle(ticker.upper(), expiry_date, call_strike, put_strike, qty=qty)

        elif spread_type == "vertical":
            if strike is None or width is None:
                console.print("[red]--strike (long strike) and --width (spread width) are required for vertical[/red]")
                raise typer.Exit(1)
            long_strike = strike
            short_strike = strike + width
            long_sym = alpaca.build_option_symbol(ticker.upper(), expiry_date, "call", long_strike)
            short_sym = alpaca.build_option_symbol(ticker.upper(), expiry_date, "call", short_strike)
            console.print(f"Placing [cyan]vertical spread[/cyan]: buy {long_sym} / sell {short_sym} x{qty}...")
            leg1 = {"symbol": long_sym, "ratio_qty": 1.0, "side": "buy", "position_intent": "buy_to_open"}
            leg2 = {"symbol": short_sym, "ratio_qty": 1.0, "side": "sell", "position_intent": "sell_to_open"}
            order = alpaca.place_spread_order(leg1, leg2, qty=qty)

        elif spread_type == "condor":
            if strike is None or width is None:
                console.print("[red]--strike (lowest strike) and --width (wing width) are required for condor[/red]")
                raise typer.Exit(1)
            s1, s2, s3, s4 = strike, strike + width, strike + width * 2, strike + width * 3
            put_buy = alpaca.build_option_symbol(ticker.upper(), expiry_date, "put", s1)
            put_sell = alpaca.build_option_symbol(ticker.upper(), expiry_date, "put", s2)
            call_sell = alpaca.build_option_symbol(ticker.upper(), expiry_date, "call", s3)
            call_buy = alpaca.build_option_symbol(ticker.upper(), expiry_date, "call", s4)
            console.print(f"Placing [cyan]iron condor[/cyan] on {ticker.upper()} {expiry}: {s1}/{s2}/{s3}/{s4} x{qty}...")
            legs = [
                {"symbol": put_buy, "ratio_qty": 1.0, "side": "buy", "position_intent": "buy_to_open"},
                {"symbol": put_sell, "ratio_qty": 1.0, "side": "sell", "position_intent": "sell_to_open"},
                {"symbol": call_sell, "ratio_qty": 1.0, "side": "sell", "position_intent": "sell_to_open"},
                {"symbol": call_buy, "ratio_qty": 1.0, "side": "buy", "position_intent": "buy_to_open"},
            ]
            order = alpaca.place_iron_condor(legs, qty=qty)

    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Order failed:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(order)
        return

    console.print(f"[green]Spread order placed:[/green] {order.get('id', '—')}")
    console.print(f"  Status: {order.get('status', '—')}")
    legs_data = order.get("legs") or []
    for i, leg in enumerate(legs_data, 1):
        console.print(f"  Leg {i}: {leg.get('symbol', '—')} {leg.get('side', '—')}")


# --- cancel command ---

@app.command()
def cancel(
    order_id: str = typer.Argument(..., help="Order ID to cancel"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Cancel an open order."""
    try:
        alpaca.cancel_order(order_id)
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Cancel failed:[/red] {e}")
        raise typer.Exit(1)

    result = {"success": True, "order_id": order_id, "message": "Order cancelled"}
    if json_output:
        _print_json(result)
        return

    console.print(f"[green]Cancelled order:[/green] {order_id}")


# --- watchlist command group ---

watchlist_app = typer.Typer(help="Manage watchlist")
app.add_typer(watchlist_app, name="watchlist")


@watchlist_app.command("list")
def watchlist_list(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all symbols in the watchlist."""
    asyncio.run(db.init_db())
    items = asyncio.run(db.watchlist_list())

    if json_output:
        _print_json(items)
        return

    if not items:
        console.print("[dim]Watchlist is empty. Use 'alpaca-trader watchlist add SYMBOL' to add symbols.[/dim]")
        return

    table = Table(title=f"Watchlist ({len(items)} symbols)")
    table.add_column("Symbol", style="bold cyan")
    table.add_column("Added")
    table.add_column("Notes")

    for item in items:
        table.add_row(
            item["symbol"],
            str(item.get("added_at", "—"))[:19],
            item.get("notes") or "—",
        )

    console.print(table)


@watchlist_app.command("add")
def watchlist_add(
    symbol: str = typer.Argument(..., help="Ticker symbol to add"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Optional notes"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Add a symbol to the watchlist."""
    asyncio.run(db.init_db())
    added = asyncio.run(db.watchlist_add(symbol.upper(), notes))

    result = {"success": added, "symbol": symbol.upper()}
    if not added:
        result["message"] = f"{symbol.upper()} is already in the watchlist"
    else:
        result["message"] = f"{symbol.upper()} added to watchlist"

    if json_output:
        _print_json(result)
        return

    if added:
        console.print(f"[green]Added[/green] {symbol.upper()} to watchlist")
    else:
        console.print(f"[yellow]{symbol.upper()} is already in the watchlist[/yellow]")


@watchlist_app.command("rm")
def watchlist_remove(
    symbol: str = typer.Argument(..., help="Ticker symbol to remove"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Remove a symbol from the watchlist."""
    asyncio.run(db.init_db())
    removed = asyncio.run(db.watchlist_remove(symbol.upper()))

    result = {"success": removed, "symbol": symbol.upper()}
    if not removed:
        result["message"] = f"{symbol.upper()} was not in the watchlist"
    else:
        result["message"] = f"{symbol.upper()} removed from watchlist"

    if json_output:
        _print_json(result)
        return

    if removed:
        console.print(f"[red]Removed[/red] {symbol.upper()} from watchlist")
    else:
        console.print(f"[yellow]{symbol.upper()} was not in the watchlist[/yellow]")


# --- scan command ---

@app.command()
def scan(
    strategy: str = typer.Option("squeeze", "--strategy", help="Strategy: squeeze, bounce, trend, bb_rsi_reversal"),
    period: str = typer.Option("1D", "--period", help="Bar timeframe: 1D, 1H, 15Min, 5Min, 1Min"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Scan watchlist symbols with a Bollinger Band strategy."""
    valid_strategies = ("squeeze", "bounce", "trend", "bb_rsi_reversal")
    if strategy not in valid_strategies:
        console.print(f"[red]Invalid strategy.[/red] Choose from: {', '.join(valid_strategies)}")
        raise typer.Exit(1)

    asyncio.run(db.init_db())
    watchlist_items = asyncio.run(db.watchlist_list())
    symbols = [item["symbol"] for item in watchlist_items]

    if not symbols:
        msg = {"error": "Watchlist is empty. Add symbols with: alpaca-trader watchlist add TICKER"}
        if json_output:
            _print_json(msg)
        else:
            console.print("[yellow]Watchlist is empty.[/yellow] Add symbols with: alpaca-trader watchlist add TICKER")
        raise typer.Exit(0)

    try:
        scanner = WatchlistScanner()
        signals = scanner.scan(symbols, strategy=strategy, period=period)
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Scan error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json([
            {
                "symbol": s.symbol,
                "strategy": s.strategy,
                "detected": s.detected,
                "direction": s.direction,
                "strength": s.strength,
                "details": s.details,
                "timestamp": s.timestamp,
            }
            for s in signals
        ])
        return

    table = Table(title=f"Bollinger Scan: {strategy.upper()} ({len(signals)} symbols, {period})")
    table.add_column("Symbol", style="bold cyan")
    table.add_column("Signal")
    table.add_column("Direction")
    table.add_column("Strength", justify="right")
    table.add_column("Details")

    for s in signals:
        detected_str = "[green]YES[/green]" if s.detected else "[dim]no[/dim]"
        direction_str = (
            f"[green]{s.direction}[/green]" if s.direction == "long"
            else f"[red]{s.direction}[/red]" if s.direction == "short"
            else f"[dim]{s.direction}[/dim]"
        )
        strength_str = f"{s.strength:.2f}" if s.detected else "—"
        detail_str = ", ".join(f"{k}={v}" for k, v in s.details.items()) if s.details else "—"

        table.add_row(s.symbol, detected_str, direction_str, strength_str, detail_str)

    console.print(table)


# --- backtest command ---

@app.command()
def backtest(
    ticker: str = typer.Argument(..., help="Ticker symbol to backtest"),
    strategy: str = typer.Option(..., "--strategy", help="Strategy: squeeze, bounce, trend, bb_rsi_reversal"),
    start: str = typer.Option(..., "--start", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--end", help="End date (YYYY-MM-DD)"),
    capital: float = typer.Option(10000.0, "--capital", help="Initial capital (default $10,000)"),
    period: str = typer.Option("1D", "--period", help="Bar timeframe: 1D, 1H, 15Min"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Run a Bollinger Band strategy backtest on a ticker."""
    valid_strategies = ("squeeze", "bounce", "trend", "bb_rsi_reversal")
    if strategy not in valid_strategies:
        console.print(f"[red]Invalid strategy.[/red] Choose from: {', '.join(valid_strategies)}")
        raise typer.Exit(1)

    # Validate dates
    try:
        datetime.fromisoformat(start)
        datetime.fromisoformat(end)
    except ValueError as e:
        console.print(f"[red]Invalid date:[/red] {e}")
        raise typer.Exit(1)

    try:
        bt = Backtester()
        result = bt.run(
            symbol=ticker.upper(),
            strategy=strategy,
            start_date=start,
            end_date=end,
            initial_capital=capital,
            period=period,
        )
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Backtest error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        import dataclasses
        _print_json(dataclasses.asdict(result))
        return

    # Human-readable output
    console.print(Panel(
        f"[bold]{ticker.upper()}[/bold] — {strategy.upper()} strategy\n"
        f"{start} → {end}  |  {result.num_trades} trades",
        title="Backtest Result",
    ))

    summary = Table(show_header=False, box=None)
    summary.add_column("Metric", style="dim", width=22)
    summary.add_column("Value")

    summary.add_row("Initial Capital", f"${result.initial_capital:,.2f}")
    summary.add_row("Final Capital", f"${result.final_capital:,.2f}")
    rtn_color = "green" if result.total_return >= 0 else "red"
    summary.add_row("Total Return", f"[{rtn_color}]{result.total_return:+.2f}%[/{rtn_color}]")
    summary.add_row("Win Rate", f"{result.win_rate*100:.1f}%")
    summary.add_row("Sharpe Ratio", f"{result.sharpe:.3f}")
    dd_color = "red" if result.max_drawdown < -5 else "yellow" if result.max_drawdown < 0 else "green"
    summary.add_row("Max Drawdown", f"[{dd_color}]{result.max_drawdown:.2f}%[/{dd_color}]")
    console.print(summary)

    if result.trades:
        console.print(f"\n[dim]Last 5 trades:[/dim]")
        trade_table = Table()
        trade_table.add_column("Entry Date", style="dim")
        trade_table.add_column("Exit Date", style="dim")
        trade_table.add_column("Dir")
        trade_table.add_column("Entry", justify="right")
        trade_table.add_column("Exit", justify="right")
        trade_table.add_column("P&L %", justify="right")

        for t in result.trades[-5:]:
            pnl_color = "green" if t.pnl_pct >= 0 else "red"
            trade_table.add_row(
                t.entry_date[:10],
                t.exit_date[:10],
                f"[green]{t.direction}[/green]" if t.direction == "long" else f"[red]{t.direction}[/red]",
                f"${t.entry_price:.2f}",
                f"${t.exit_price:.2f}",
                f"[{pnl_color}]{t.pnl_pct:+.2f}%[/{pnl_color}]",
            )
        console.print(trade_table)


# --- alert command group ---

alert_app = typer.Typer(help="Manage price and strategy alerts")
app.add_typer(alert_app, name="alert")


@alert_app.command("list")
def alert_list(
    status: Optional[str] = typer.Option(None, "--status", help="Filter: active, triggered, dismissed"),
    alert_type: Optional[str] = typer.Option(None, "--type", help="Filter by type"),
    symbol: Optional[str] = typer.Option(None, "--symbol", help="Filter by symbol"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List alerts."""
    asyncio.run(db.init_db())
    items = asyncio.run(db.alerts_list(status=status, alert_type=alert_type, symbol=symbol))

    if json_output:
        _print_json(items)
        return

    if not items:
        console.print("[dim]No alerts found.[/dim]")
        return

    table = Table(title=f"Alerts ({len(items)})")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Type", style="cyan")
    table.add_column("Symbol", style="bold")
    table.add_column("Condition")
    table.add_column("Status")
    table.add_column("Message")
    table.add_column("Created")

    for item in items:
        condition = item.get("condition", {})
        cond_str = ", ".join(f"{k}={v}" for k, v in condition.items()) if condition else "—"
        status_val = item.get("status", "—")
        status_styled = (
            f"[green]{status_val}[/green]" if status_val == "active"
            else f"[yellow]{status_val}[/yellow]" if status_val == "triggered"
            else f"[dim]{status_val}[/dim]"
        )
        table.add_row(
            str(item.get("id", "—")),
            item.get("alert_type", "—"),
            item.get("symbol", "—"),
            cond_str,
            status_styled,
            item.get("message") or "—",
            str(item.get("created_at", "—"))[:19],
        )

    console.print(table)


@alert_app.command("add")
def alert_add_cmd(
    alert_type: str = typer.Argument(..., help="Alert type: pnl, expiry, price, squeeze, signal, fill"),
    symbol: str = typer.Argument(..., help="Ticker symbol"),
    threshold: Optional[float] = typer.Option(None, "--threshold", help="P&L threshold % (for pnl type)"),
    days: Optional[int] = typer.Option(None, "--days", help="Days to expiry (for expiry type)"),
    target: Optional[float] = typer.Option(None, "--target", help="Price target (for price type)"),
    direction: str = typer.Option("above", "--direction", help="Price direction: above, below"),
    strategy: str = typer.Option("bounce", "--strategy", help="Strategy for signal type: bounce, trend"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Add an alert. Types: pnl, expiry, price, squeeze, signal, fill."""
    valid_types = ("pnl", "expiry", "price", "squeeze", "signal", "fill")
    if alert_type not in valid_types:
        console.print(f"[red]Invalid alert type.[/red] Choose from: {', '.join(valid_types)}")
        raise typer.Exit(1)

    condition: dict = {}
    if alert_type == "pnl":
        if threshold is None:
            console.print("[red]--threshold required for pnl alert[/red]")
            raise typer.Exit(1)
        condition = {"threshold": threshold}
    elif alert_type == "expiry":
        condition = {"days": days or 7}
    elif alert_type == "price":
        if target is None:
            console.print("[red]--target required for price alert[/red]")
            raise typer.Exit(1)
        condition = {"target_price": target, "direction": direction}
    elif alert_type == "signal":
        condition = {"strategy": strategy}
    elif alert_type in ("squeeze", "fill"):
        condition = {}

    asyncio.run(db.init_db())
    alert_id = asyncio.run(db.alerts_add(alert_type, symbol.upper(), condition))

    result = {"id": alert_id, "alert_type": alert_type, "symbol": symbol.upper(), "condition": condition}
    if json_output:
        _print_json(result)
        return

    console.print(f"[green]Alert #{alert_id} created:[/green] {alert_type} on {symbol.upper()}")
    if condition:
        console.print(f"  Condition: {', '.join(f'{k}={v}' for k, v in condition.items())}")


@alert_app.command("dismiss")
def alert_dismiss(
    alert_id: int = typer.Argument(..., help="Alert ID to dismiss"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Dismiss an alert by ID."""
    asyncio.run(db.init_db())
    ok = asyncio.run(db.alerts_dismiss(alert_id))

    result = {"success": ok, "id": alert_id}
    if json_output:
        _print_json(result)
        return

    if ok:
        console.print(f"[green]Alert #{alert_id} dismissed.[/green]")
    else:
        console.print(f"[yellow]Alert #{alert_id} not found.[/yellow]")


@alert_app.command("check")
def alert_check(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Run alert check now and show triggered alerts."""
    asyncio.run(db.init_db())
    try:
        checker = AlertChecker()
        triggered = asyncio.run(checker.check_all())
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Check error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(triggered)
        return

    if not triggered:
        console.print("[dim]No alerts triggered.[/dim]")
        return

    console.print(f"[yellow]🔔 {len(triggered)} alert(s) triggered:[/yellow]")
    for a in triggered:
        console.print(f"  [cyan]#{a['id']}[/cyan] {a.get('message', '—')}")


@alert_app.command("send-test")
def alert_send_test(
    symbol: str = typer.Option("AAPL", "--symbol", help="Symbol for the test alert"),
    alert_type: str = typer.Option("price", "--type", help="Alert type for the test alert"),
    severity: str = typer.Option("info", "--severity", help="Severity: info, warning, critical"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Queue a test alert to verify the delivery pipeline."""
    test_alert = {
        "id": "test-0",
        "alert_type": alert_type,
        "symbol": symbol.upper(),
        "message": f"Test alert: {alert_type} on {symbol.upper()}",
        "status": "triggered",
    }
    context: dict = {}
    if alert_type == "price":
        context = {"price": "150.00", "target": "148.00"}
    elif alert_type == "pnl":
        context = {"pct": "5.2", "value": "260.00"}
    elif alert_type == "fill":
        context = {"side": "buy", "qty": "1", "price": "150.00"}
    elif alert_type == "expiry":
        context = {"days": "3", "value": "-45.00"}
    elif alert_type == "squeeze":
        context = {"width": "0.042"}
    elif alert_type == "signal":
        context = {"strategy": "bounce", "direction": "bullish", "score": "0.78"}

    delivery = TelegramDeliveryQueue()
    queue_id = delivery.queue_alert(test_alert, context=context, severity=severity)
    formatted = format_alert_telegram({**test_alert, "context": context, "severity": severity})

    result = {"queue_id": queue_id, "text": formatted}
    if json_output:
        _print_json(result)
        return

    console.print(f"[green]Test alert queued[/green] (id: {queue_id})")
    console.print(f"  Message: {formatted}")


@alert_app.command("queue")
def alert_queue_cmd(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    all_alerts: bool = typer.Option(False, "--all", help="Show delivered alerts too"),
):
    """Show pending alerts in the delivery queue."""
    from alpaca_trader.alerts.delivery import _load_queue  # type: ignore[attr-defined]

    queue = _load_queue()
    if not all_alerts:
        queue = [e for e in queue if not e.get("delivered")]

    if json_output:
        _print_json(queue)
        return

    if not queue:
        console.print("[dim]No pending alerts in queue.[/dim]")
        return

    table = Table(title=f"Alert Queue ({len(queue)})")
    table.add_column("Queue ID", style="dim", width=8)
    table.add_column("Alert ID", style="dim", width=8)
    table.add_column("Type", style="cyan")
    table.add_column("Symbol", style="bold")
    table.add_column("Severity")
    table.add_column("Message")
    table.add_column("Triggered At")
    table.add_column("Delivered")

    for entry in queue:
        queue_id_short = str(entry.get("queue_id", ""))[:8]
        delivered = entry.get("delivered", False)
        delivered_str = "[green]yes[/green]" if delivered else "[yellow]pending[/yellow]"
        severity = entry.get("severity", "info")
        sev_styled = (
            f"[red]{severity}[/red]" if severity == "critical"
            else f"[yellow]{severity}[/yellow]" if severity == "warning"
            else f"[dim]{severity}[/dim]"
        )
        table.add_row(
            queue_id_short,
            str(entry.get("alert_id", "—")),
            entry.get("alert_type", "—"),
            entry.get("symbol", "—"),
            sev_styled,
            entry.get("message", "—")[:60],
            str(entry.get("triggered_at", "—"))[:19],
            delivered_str,
        )

    console.print(table)


# --- monitor command group ---

monitor_app = typer.Typer(help="Monitor market and run scheduled scans")
app.add_typer(monitor_app, name="monitor")


@monitor_app.command("run")
def monitor_run(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Run full scan + alert check (one-shot)."""
    asyncio.run(db.init_db())
    try:
        scanner = ScheduledScanner()
        results = asyncio.run(scanner.run())
    except EnvironmentError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Monitor error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(results)
        return

    console.print(Panel(
        f"Scanned [cyan]{results['symbols_scanned']}[/cyan] symbols\n"
        f"Started: {results['started_at'][:19]}  Completed: {results['completed_at'][:19]}",
        title="Monitor Run",
    ))
    console.print(results.get("summary", ""))


@monitor_app.command("status")
def monitor_status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show last scan time and active alert count."""
    asyncio.run(db.init_db())
    last_run = asyncio.run(db.setting_get("monitor_last_run"))
    last_count = asyncio.run(db.setting_get("monitor_last_triggered_count"))
    active_alerts = asyncio.run(db.alerts_list(status="active"))

    result = {
        "last_run": last_run or "never",
        "last_triggered_count": int(last_count or 0),
        "active_alerts": len(active_alerts),
    }

    if json_output:
        _print_json(result)
        return

    t = Table(title="Monitor Status", show_header=False, box=None)
    t.add_column("Field", style="dim", width=24)
    t.add_column("Value")
    t.add_row("Last Run", last_run or "[dim]never[/dim]")
    t.add_row("Last Triggered", str(last_count or 0))
    t.add_row("Active Alerts", str(len(active_alerts)))
    console.print(t)


# --- serve command ---

@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Host to bind"),
    port: int = typer.Option(8080, "--port", help="Port to listen on"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev mode)"),
):
    """Start the FastAPI server."""
    import uvicorn
    console.print(f"Starting alpaca-trader API on [cyan]http://{host}:{port}[/cyan]")
    uvicorn.run(
        "alpaca_trader.api.app:app",
        host=host,
        port=port,
        reload=reload,
    )


# --- auto command group ---

auto_app = typer.Typer(help="Auto-trading engine control")
app.add_typer(auto_app, name="auto")


@auto_app.command("status")
def auto_status(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show auto-trading engine state (enabled, circuit breaker, trades today, journal stats)."""
    from alpaca_trader.engine.auto_trader import AutoTrader
    asyncio.run(db.init_db())
    trader = AutoTrader()
    result = asyncio.run(trader.status())

    if json_output:
        _print_json(result)
        return

    t = Table(title="Auto-Trader Status", show_header=False, box=None)
    t.add_column("Field", style="dim", width=26)
    t.add_column("Value")

    enabled_str = "[green]YES[/green]" if result["enabled"] else "[red]NO[/red]"
    cb_str = "[red]TRIPPED[/red]" if result["circuit_breaker"] else "[green]OK[/green]"
    market_str = "[green]OPEN[/green]" if result["market_open"] else "[dim]closed[/dim]"
    dry_str = "[yellow]dry-run[/yellow]" if result["dry_run"] else "[green]LIVE[/green]"

    t.add_row("Enabled", enabled_str)
    t.add_row("Mode", dry_str)
    t.add_row("Market", market_str)
    t.add_row("Circuit Breaker", cb_str)
    if result["circuit_breaker"] and result["circuit_breaker_reason"]:
        t.add_row("CB Reason", result["circuit_breaker_reason"])
    t.add_row("Trades Today", str(result["trades_today"]))
    t.add_row("Closed Trades", str(result["closed_trades"]))
    t.add_row("Paper Lockout Remaining", str(result["paper_lockout_remaining"]))

    stats = result.get("journal_stats", {})
    if stats and stats.get("total_trades", 0) > 0:
        t.add_row("Win Rate", f"{stats['win_rate']*100:.1f}%")
        t.add_row("Avg P&L", _fmt_decimal(stats["avg_pnl"]))
        t.add_row("Total P&L", _fmt_decimal(stats["total_pnl"]))

    console.print(t)


@auto_app.command("enable")
def auto_enable(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Enable auto-trading."""
    from alpaca_trader.engine.auto_trader import AutoTrader
    asyncio.run(db.init_db())
    trader = AutoTrader()
    asyncio.run(trader.enable())
    result = {"success": True, "message": "Auto-trading enabled"}
    if json_output:
        _print_json(result)
        return
    console.print("[green]Auto-trading enabled.[/green]")


@auto_app.command("disable")
def auto_disable(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Disable auto-trading."""
    from alpaca_trader.engine.auto_trader import AutoTrader
    asyncio.run(db.init_db())
    trader = AutoTrader()
    asyncio.run(trader.disable())
    result = {"success": True, "message": "Auto-trading disabled"}
    if json_output:
        _print_json(result)
        return
    console.print("[yellow]Auto-trading disabled.[/yellow]")


@auto_app.command("run")
def auto_run(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Run one auto-trade cycle manually (for testing)."""
    from alpaca_trader.engine.auto_trader import AutoTrader
    asyncio.run(db.init_db())
    trader = AutoTrader()
    try:
        summary = asyncio.run(trader.run_cycle())
    except Exception as e:
        console.print(f"[red]Cycle error:[/red] {e}")
        raise typer.Exit(1)

    if json_output:
        _print_json(summary)
        return

    console.print(Panel(
        f"Market open: {'[green]yes[/green]' if summary['market_open'] else '[dim]no[/dim]'}  |  "
        f"Enabled: {'[green]yes[/green]' if summary['enabled'] else '[red]no[/red]'}\n"
        f"Exits checked: {summary['exits_checked']}  executed: {summary['exits_executed']}\n"
        f"Signals found: {summary['signals_found']}  entries: {summary['entries_executed']}",
        title=f"Auto-Trade Cycle — {summary['cycle_time'][:19]}",
    ))
    if summary.get("errors"):
        console.print("[red]Errors:[/red]")
        for err in summary["errors"]:
            console.print(f"  [dim]• {err}[/dim]")


# --- journal command group ---

journal_app = typer.Typer(help="Trade journal — view and analyze trade history")
app.add_typer(journal_app, name="journal")


@journal_app.command("list")
def journal_list(
    limit: int = typer.Option(50, "--limit", help="Number of trades to show"),
    strategy: Optional[str] = typer.Option(None, "--strategy", help="Filter by strategy"),
    status: Optional[str] = typer.Option(None, "--status", help="Filter: open, closed"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show recent trades from the journal."""
    from alpaca_trader.engine.trade_journal import TradeJournal
    asyncio.run(db.init_db())
    journal = TradeJournal()
    trades = asyncio.run(journal.get_trades(limit=limit, strategy=strategy, status=status))

    if json_output:
        _print_json(trades)
        return

    if not trades:
        console.print("[dim]No trades found.[/dim]")
        return

    table = Table(title=f"Trade Journal ({len(trades)} trades)")
    table.add_column("ID", style="dim", width=5)
    table.add_column("Symbol", style="bold cyan")
    table.add_column("Side")
    table.add_column("Qty", justify="right")
    table.add_column("Entry $", justify="right")
    table.add_column("Exit $", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("P&L %", justify="right")
    table.add_column("Strategy")
    table.add_column("Status")
    table.add_column("Entry Time", style="dim")

    for t in trades:
        pnl = t.get("pnl")
        pnl_pct = t.get("pnl_pct")
        status_val = t.get("status", "open")
        status_str = "[green]closed[/green]" if status_val == "closed" else "[yellow]open[/yellow]"
        side_str = "[green]buy[/green]" if t.get("side") == "buy" else "[red]sell[/red]"
        table.add_row(
            str(t.get("id", "—")),
            t.get("symbol", "—"),
            side_str,
            str(t.get("qty", "—")),
            _fmt_decimal(t.get("entry_price")),
            _fmt_decimal(t.get("exit_price")) if t.get("exit_price") else "—",
            _fmt_decimal(pnl) if pnl is not None else "—",
            _fmt_pct(pnl_pct) if pnl_pct is not None else "—",
            t.get("strategy") or "—",
            status_str,
            str(t.get("entry_time", "—"))[:19],
        )

    console.print(table)


@journal_app.command("stats")
def journal_stats(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show trade journal statistics: win rate, P&L, trade count."""
    from alpaca_trader.engine.trade_journal import TradeJournal
    asyncio.run(db.init_db())
    journal = TradeJournal()
    stats = asyncio.run(journal.get_stats())
    count = asyncio.run(journal.get_trade_count())

    if json_output:
        _print_json({**stats, "closed_trades": count})
        return

    t = Table(title="Journal Statistics", show_header=False, box=None)
    t.add_column("Metric", style="dim", width=26)
    t.add_column("Value")

    t.add_row("Closed Trades", str(stats["total_trades"]))
    t.add_row("Open Trades", str(stats["open_trades"]))
    t.add_row("Win Rate", f"{stats['win_rate']*100:.1f}%")
    t.add_row("Avg P&L per Trade", _fmt_decimal(stats["avg_pnl"]))
    t.add_row("Total P&L", _fmt_decimal(stats["total_pnl"]))
    t.add_row("Sharpe (raw)", f"{stats['sharpe']:.3f}")
    remaining = max(0, 50 - count)
    t.add_row("Paper Lockout Remaining", str(remaining))

    console.print(t)


if __name__ == "__main__":
    app()
