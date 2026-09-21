# Paper Portfolio Accounting Schema

Schema version: 2
Effective: 2026-09-21
Accounting method: weighted-average cost

The paper portfolio has three canonical record types:

1. `state.json` — mutable current portfolio state.
2. `trades.jsonl` — append-only immutable execution ledger.
3. `snapshots/*.json` — immutable timestamped portfolio checkpoints.

## state.json

Portfolio-level fields should include:

```json
{
  "schema_version": 2,
  "portfolio_id": "regime-framework-10k-2026-09-09",
  "current_cash_usd": 0,
  "realized_pnl_usd": 0,
  "current_nav_usd": 0,
  "benchmark_nav_usd": 0,
  "alpha_vs_benchmark_usd": 0,
  "alpha_vs_benchmark_bps": 0,
  "total_unrealized_pnl_usd": 0,
  "last_full_mark_at_utc": "ISO-8601 timestamp"
}
```

Each open position should include:

```json
{
  "quantity": 0,
  "average_cost_usd": 0,
  "total_cost_basis_usd": 0,
  "current_mark_usd": 0,
  "current_mark_at_utc": "ISO-8601 timestamp",
  "mark_source": "source description",
  "marked_value_usd": 0,
  "unrealized_pnl_usd": 0,
  "unrealized_pnl_pct": 0,
  "realized_pnl_usd": 0,
  "portfolio_weight_pct": 0,
  "signal_id": "research signal/observation identifier or null",
  "latest_trade_id": "trade ledger identifier"
}
```

Definitions:

- `total_cost_basis_usd = quantity * average_cost_usd`.
- `marked_value_usd = quantity * current_mark_usd`.
- `unrealized_pnl_usd = marked_value_usd - total_cost_basis_usd`.
- `unrealized_pnl_pct = unrealized_pnl_usd / total_cost_basis_usd * 100` when cost basis is nonzero.
- `portfolio_weight_pct = marked_value_usd / current_nav_usd * 100`.
- Transaction costs on buys are included in weighted-average cost.
- Transaction costs on sells reduce realized proceeds/P&L.

## trades.jsonl

One JSON object per line. Existing lines are immutable.

Required fields for every future generated trade:

```json
{
  "schema_version": 2,
  "trade_id": "BUY-...",
  "signal_id": "observation/signal identifier or null",
  "signal_record_path": "observations/... or null",
  "timestamp_utc": "ISO-8601 timestamp",
  "action": "BUY|ADD|TRIM|SELL",
  "asset": "ticker",
  "contract_address": null,
  "quantity": 0,
  "mark_price_usd": 0,
  "fill_price_usd": 0,
  "price_source": "source",
  "gross_usd": 0,
  "transaction_cost_rate": 0,
  "transaction_cost_usd": 0,

  "position_before": {
    "quantity": 0,
    "average_cost_usd": 0,
    "total_cost_basis_usd": 0,
    "marked_value_usd": 0,
    "unrealized_pnl_usd": 0,
    "portfolio_weight_pct": 0
  },

  "realized_pnl_this_trade_usd": 0,
  "cumulative_realized_pnl_asset_usd": 0,

  "position_after": {
    "quantity": 0,
    "average_cost_usd": 0,
    "total_cost_basis_usd": 0,
    "current_mark_usd": 0,
    "marked_value_usd": 0,
    "unrealized_pnl_usd": 0,
    "unrealized_pnl_pct": 0,
    "portfolio_weight_pct": 0
  },

  "cash_after_usd": 0,
  "portfolio_nav_after_usd": 0,
  "passive_benchmark_nav_usd": 0,
  "alpha_vs_benchmark_usd": 0,
  "alpha_vs_benchmark_bps": 0,

  "structural_gate": "PASS|FAIL|PASS_WITH_CAVEATS",
  "regime_classification": "text",
  "rationale": "prospective rationale"
}
```

For BUY/ADD, `realized_pnl_this_trade_usd` is 0. For TRIM/SELL it is mandatory and must be calculated before the forward outcome is known.

## Hourly marking

Every hourly regime scan must:

1. Read `state.json` and `trades.jsonl` first.
2. Obtain current independently verifiable USD marks for every open position.
3. Recompute all position-level marked value, unrealized P&L and weight fields.
4. Recompute portfolio NAV and passive benchmark NAV.
5. Persist the refreshed state even if the run generates no trade and no user alert.
6. If a trade occurs, append one immutable schema-v2 line to `trades.jsonl`, then update `state.json`.
7. Never rewrite old trade lines to improve hindsight or fill missing schema-v1 fields.

## Signal IDs

A generated trade should point to the research evidence that authorized it. Prefer the immutable observation filename or another stable research signal identifier. If the trade is generated without a separate saved observation, store `signal_id: null` explicitly rather than inventing an identifier.
