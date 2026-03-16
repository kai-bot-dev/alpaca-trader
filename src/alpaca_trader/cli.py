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

from alpaca_trader.core import client as alpaca
from alpaca_trader.core import database as db
from alpaca_trader.strategies.scanner import WatchlistScanner
from alpaca_trader.strategies.backtest import Backtester

app = typer.Typer(
    name="alpaca-trader",
    help="Alpaca options paper trading CLI",
    add_completion=False,
)

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
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show current open positions with P&L."""
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
        status_val = o.get("status", "—")
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
    strategy: str = typer.Option("squeeze", "--strategy", help="Strategy: squeeze, bounce, trend"),
    period: str = typer.Option("1D", "--period", help="Bar timeframe: 1D, 1H, 15Min, 5Min, 1Min"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Scan watchlist symbols with a Bollinger Band strategy."""
    valid_strategies = ("squeeze", "bounce", "trend")
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
    strategy: str = typer.Option(..., "--strategy", help="Strategy: squeeze, bounce, trend"),
    start: str = typer.Option(..., "--start", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(..., "--end", help="End date (YYYY-MM-DD)"),
    capital: float = typer.Option(10000.0, "--capital", help="Initial capital (default $10,000)"),
    period: str = typer.Option("1D", "--period", help="Bar timeframe: 1D, 1H, 15Min"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Run a Bollinger Band strategy backtest on a ticker."""
    valid_strategies = ("squeeze", "bounce", "trend")
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


if __name__ == "__main__":
    app()
