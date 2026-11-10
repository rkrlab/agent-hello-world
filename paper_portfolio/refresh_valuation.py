"""Validate the paper ledger and refresh only the mutable valuation fields."""

import argparse
import copy
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
INITIAL = "snapshots/2026-09-09T1514Z-initial.json"
# Explicit provider IDs prevent collisions with wrapped coins and reused tickers.
ASSETS = {
    "BTC": ("bitcoin", "btc-bitcoin"),
    "ETH": ("ethereum", "eth-ethereum"),
    "SOL": ("solana", "sol-solana"),
    "SUI": ("sui", "sui-sui"),
    "BNB": ("binancecoin", "bnb-binance-coin"),
    "UNI": ("uniswap", "uni-uniswap"),
    "HYPE": ("hyperliquid", "hype-hyperliquid"),
    "ZEC": ("zcash", "zec-zcash"),
    "AERO": ("aerodrome-finance", "aero-aerodrome-finance"),
}
GECKO = "https://api.coingecko.com/api/v3/simple/price"
PAPRIKA = "https://api.coinpaprika.com/v1/tickers"
MAX_AGE = timedelta(minutes=5)
MAX_SKEW = timedelta(minutes=2)
USD_TOLERANCE = Decimal("0.000001")
QUANTITY_TOLERANCE = Decimal("0.0000000001")
ZERO = Decimal(0)


class Mark(NamedTuple):
    price: Decimal
    timestamp: datetime
    source: str


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    result = Decimal(str(value))
    require(result.is_finite(), "Non-finite number")
    return result


def close(actual, expected, label, tolerance=USD_TOLERANCE):
    require(abs(number(actual) - expected) <= tolerance, f"{label}: {actual} != {expected}")


def timestamp(value):
    result = datetime.fromisoformat(value)
    require(result.utcoffset() is not None, f"Timestamp lacks offset: {value}")
    return result.astimezone(timezone.utc)


def utc(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def reconcile(state, ledger, initial):
    require(state["schema_version"] == 2, "Expected state schema v2")
    require(state["base_currency"] == "USD", "Expected USD base currency")
    require(state["accounting_method"] == "weighted_average_cost", "Unsupported cost method")
    require(ledger and ledger[0]["action"] == "INITIALIZE", "Missing opening ledger record")
    opening = ledger[0]
    last_time = timestamp(opening["timestamp_utc"])
    require(last_time == timestamp(initial["timestamp_utc"]) ==
            timestamp(state["initialized_at_utc"]), "Opening timestamps disagree")
    seen = {opening["trade_id"]}
    cash = number(initial["cash_usd"])
    close(opening["cash_after_usd"], cash, "Opening ledger cash")
    starting_nav = number(initial["nav_usd"])
    close(opening["gross_usd"], starting_nav, "Opening ledger NAV")
    close(state["starting_nav_usd"], starting_nav, "Starting NAV")
    benchmark = state["benchmark"]
    require(benchmark["type"] == "passive_hold_opening_allocation", "Unsupported benchmark")
    close(benchmark["cash_usd"], cash, "Benchmark cash")
    close(benchmark["starting_nav_usd"], starting_nav, "Benchmark starting NAV")
    opening_marks = initial["market_marks"]
    require(benchmark["quantities"].keys() == opening_marks.keys(), "Benchmark assets disagree")
    quantities, costs, realized, latest = {}, {}, {}, {}
    for asset, mark in opening_marks.items():
        quantities[asset] = number(mark["quantity"])
        costs[asset] = quantities[asset] * number(mark["price_usd"])
        require(quantities[asset] > 0 and costs[asset] > 0, f"{asset}: invalid opening basis")
        realized[asset] = ZERO
        latest[asset] = opening["trade_id"]
        close(benchmark["quantities"][asset], quantities[asset], f"{asset} benchmark units",
              QUANTITY_TOLERANCE)
        close(mark["value_usd"], costs[asset], f"{asset} opening value")
    close(cash + sum(costs.values()), starting_nav, "Opening allocation NAV")

    for trade in ledger[1:]:
        trade_id, asset, action = (trade[key] for key in ("trade_id", "asset", "action"))
        traded_at = timestamp(trade["timestamp_utc"])
        require(trade_id not in seen and traded_at >= last_time, f"Invalid ledger order: {trade_id}")
        seen.add(trade_id)
        last_time = traded_at
        units, gross, fee = (number(trade[key]) for key in
                             ("quantity", "gross_usd", "transaction_cost_usd"))
        require(units > 0 and gross > 0 and 0 <= fee < gross, f"Invalid execution: {trade_id}")
        close(gross, units * number(trade.get("fill_price_usd", trade["mark_price_usd"])),
              f"{trade_id} gross")
        close(fee, gross * number(trade["transaction_cost_rate"]), f"{trade_id} fee")
        before = quantities.get(asset, ZERO)
        basis = costs.get(asset, ZERO)
        trade_pnl = ZERO
        if action in ("BUY", "ADD"):
            quantities[asset] = before + units
            costs[asset] = basis + gross + fee
            cash -= gross + fee
        else:
            require(action in ("SELL", "TRIM"), f"Unsupported action: {action}")
            require(before > 0 and units <= before + QUANTITY_TOLERANCE,
                    f"Sale exceeds holdings: {trade_id}")
            remaining = before - units
            if action == "SELL" and abs(remaining) <= QUANTITY_TOLERANCE:
                remaining = ZERO
            require(remaining >= 0, f"Sale exceeds holdings: {trade_id}")
            quantities[asset] = remaining
            costs[asset] = basis * remaining / before
            cash += gross - fee
            trade_pnl = gross - fee - (basis - costs[asset])
        realized[asset] = realized.get(asset, ZERO) + trade_pnl
        latest[asset] = trade_id
        require(cash >= -USD_TOLERANCE, f"Negative cash: {trade_id}")
        close(trade["cash_after_usd"], cash, f"{trade_id} cash")
        if trade.get("schema_version") == 2:
            close(trade["realized_pnl_this_trade_usd"], trade_pnl, f"{trade_id} realized P&L")
            close(trade["cumulative_realized_pnl_asset_usd"], realized[asset],
                  f"{trade_id} cumulative realized P&L")
            after_units = trade["position_after"]["quantity"]
            close(trade["position_after"]["total_cost_basis_usd"], costs[asset],
                  f"{trade_id} remaining basis")
        else:
            if action in ("SELL", "TRIM"):
                close(trade["realized_pnl_usd"], trade_pnl, f"{trade_id} realized P&L")
            after_units = trade["position_after_quantity"]
        close(after_units, quantities[asset], f"{trade_id} remaining units", QUANTITY_TOLERANCE)

    require(state["trade_count"] == len(ledger) - 1, "Execution count disagrees with ledger")
    require(state["last_trade_id"] == ledger[-1]["trade_id"], "Latest trade disagrees with ledger")
    close(state["current_cash_usd"], cash, "State cash")
    close(state["realized_pnl_usd"], sum(realized.values()), "State realized P&L")
    require(state["positions"].keys() == {a for a in quantities if quantities[a] > 0},
            "Open positions disagree with ledger")
    for asset, pos in state["positions"].items():
        close(pos["quantity"], quantities[asset], f"{asset} state units", QUANTITY_TOLERANCE)
        close(pos["total_cost_basis_usd"], costs[asset], f"{asset} state cost basis")
        close(number(pos["quantity"]) * number(pos["average_cost_usd"]), costs[asset],
              f"{asset} state weighted-average cost")
        close(pos["realized_pnl_usd"], realized[asset], f"{asset} state realized P&L")
        require(pos["latest_trade_id"] == latest[asset], f"{asset} latest trade disagrees")


def fetch_json(url, headers=None):
    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "rkrlab-paper-portfolio/1.0",
        **(headers or {}),
    })
    for attempt in range(3):
        try:
            with urlopen(request, timeout=12) as response:
                return json.load(response, parse_float=Decimal)
        except HTTPError as error:
            if attempt == 2 or (error.code != 429 and not 500 <= error.code < 600):
                raise
        except OSError:
            if attempt == 2:
                raise
        time.sleep(2 ** (attempt + 1))


def gecko_marks(assets):
    params = urlencode({
        "ids": ",".join(ASSETS[a][0] for a in assets),
        "vs_currencies": "usd",
        "include_last_updated_at": "true",
        "precision": "full",
    })
    key = os.environ.get("COINGECKO_DEMO_API_KEY")
    rows = fetch_json(f"{GECKO}?{params}", {"x-cg-demo-api-key": key} if key else None)
    marks = {}
    for asset in assets:
        coin_id = ASSETS[asset][0]
        row = rows[coin_id]
        marks[asset] = Mark(number(row["usd"]),
                            datetime.fromtimestamp(row["last_updated_at"], timezone.utc),
                            f"CoinGecko {GECKO}?ids={coin_id}&vs_currencies=usd"
                            "&include_last_updated_at=true&precision=full")
    return marks


def paprika_marks(assets):
    ids = {ASSETS[asset][1]: asset for asset in assets}
    marks = {}
    for row in fetch_json(PAPRIKA):
        coin_id = row["id"]
        if coin_id in ids:
            marks[ids[coin_id]] = Mark(number(row["quotes"]["USD"]["price"]),
                                       timestamp(row["last_updated"]), f"CoinPaprika {PAPRIKA}/{coin_id}")
    return marks


def validate_marks(assets, marks, now):
    require(marks.keys() == set(assets), f"Missing quotes: {sorted(set(assets) - marks.keys())}")
    for asset, mark in marks.items():
        require(mark.price.is_finite() and mark.price > 0, f"{asset}: invalid USD price")
        require(timedelta(0) <= now - mark.timestamp <= MAX_AGE,
                f"{asset}: stale or future quote ({utc(mark.timestamp)})")
    times = [mark.timestamp for mark in marks.values()]
    if times:
        require(max(times) - min(times) <= MAX_SKEW, "Quote timestamps span more than 2 minutes")


def live_marks(assets):
    for name, provider in (("CoinGecko", gecko_marks), ("CoinPaprika", paprika_marks)):
        try:
            marks = provider(assets)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            validate_marks(assets, marks, now)
            return marks, now
        except (ValueError, TypeError, KeyError, ArithmeticError, OSError) as error:
            print(f"{name}: {error}", file=sys.stderr)
    raise ValueError("No complete fresh quote batch")


def revalue(state, marks, now):
    positions = state["positions"]
    benchmark = state["benchmark"]
    validate_marks(set(positions) | benchmark["quantities"].keys(), marks, now)
    require(now >= timestamp(state["last_full_mark_at_utc"]), "Valuation time moved backward")
    for asset, pos in positions.items():
        require(marks[asset].timestamp >= timestamp(pos["current_mark_at_utc"]),
                f"{asset}: quote predates saved mark")
    benchmark_only = marks.keys() - positions.keys()
    previous_only = state["last_recorded_portfolio_mark"].get("benchmark_only_marks", {})
    for asset in benchmark_only & previous_only.keys():
        require(marks[asset].timestamp >= timestamp(previous_only[asset]["current_mark_at_utc"]),
                f"{asset}: benchmark quote predates saved mark")

    updated = copy.deepcopy(state)
    values = {a: number(pos["quantity"]) * marks[a].price for a, pos in positions.items()}
    nav = number(state["current_cash_usd"]) + sum(values.values())
    passive = number(benchmark["cash_usd"]) + sum(
        (number(qty) * marks[a].price for a, qty in benchmark["quantities"].items()), ZERO)
    require(nav > 0 and passive > 0, "NAV must be positive")
    total_unrealized = ZERO
    for asset, pos in updated["positions"].items():
        basis = number(pos["total_cost_basis_usd"])
        pnl = values[asset] - basis
        total_unrealized += pnl
        pos.update(mark_fields(marks[asset]), marked_value_usd=float(values[asset]),
                   unrealized_pnl_usd=float(pnl), unrealized_pnl_pct=float(pnl / basis * 100),
                   portfolio_weight_pct=float(values[asset] / nav * 100))

    realized = number(state["realized_pnl_usd"])
    close(nav, number(state["starting_nav_usd"]) + realized + total_unrealized, "NAV/P&L tie-out")
    alpha = nav - passive
    as_of = utc(now)
    updated.update(current_nav_usd=float(nav), benchmark_nav_usd=float(passive),
                   alpha_vs_benchmark_usd=float(alpha),
                   alpha_vs_benchmark_bps=float(alpha / passive * 10000),
                   total_unrealized_pnl_usd=float(total_unrealized), last_full_mark_at_utc=as_of)
    updated["last_recorded_portfolio_mark"] = {
        "timestamp_utc": as_of,
        "nav_usd": updated["current_nav_usd"],
        "benchmark_nav_usd": updated["benchmark_nav_usd"],
        "alpha_vs_benchmark_usd": updated["alpha_vs_benchmark_usd"],
        "alpha_vs_benchmark_bps": updated["alpha_vs_benchmark_bps"],
        "per_position_marks_complete": True,
        "benchmark_only_marks": {a: mark_fields(marks[a]) for a in sorted(benchmark_only)},
        "note": "Prospective mark-to-market refresh with no execution.",
    }
    return updated


def mark_fields(mark):
    return {"current_mark_usd": float(mark.price), "current_mark_at_utc": utc(mark.timestamp),
            "mark_source": mark.source}


def atomic_write(path, contents):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as file:
        temp = Path(file.name)
        try:
            file.write(contents)
            file.close()
            temp.chmod(path.stat().st_mode & 0o777)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Replace state.json after validation")
    args = parser.parse_args()
    path = ROOT / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    ledger = [json.loads(line, parse_float=Decimal) for line in
              (ROOT / "trades.jsonl").read_text(encoding="utf-8").splitlines()]
    initial = json.loads((ROOT / INITIAL).read_text(encoding="utf-8"), parse_float=Decimal)
    reconcile(state, ledger, initial)
    assets = sorted(state["positions"].keys() | state["benchmark"]["quantities"].keys())
    require(set(assets) <= ASSETS.keys(), f"Unmapped quote assets: {sorted(set(assets) - ASSETS.keys())}")
    marks, now = live_marks(assets)
    require(now >= timestamp(ledger[-1]["timestamp_utc"]), "Latest trade is in the future")
    updated = revalue(state, marks, now)
    contents = json.dumps(updated, indent=2, allow_nan=False) + "\n"
    if args.write:
        atomic_write(path, contents)
    else:
        print(contents, end="")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, TypeError, KeyError, ArithmeticError, OSError) as error:
        sys.exit(f"Valuation failed: {error}")
