"""Deterministic paper-execution engine for crypto research signals.

This module NEVER sends a transaction or touches a wallet. It converts a research
signal into an auditable simulated execution plan and emits GitHub Actions outputs.
"""

import json
import math
import os
from datetime import datetime, timezone


def env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def write_output(name: str, value: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def main() -> None:
    asset = os.getenv("ASSET", "UNKNOWN").strip()
    contract = os.getenv("CONTRACT", "unknown").strip()
    ecosystem = os.getenv("ECOSYSTEM", "unknown").strip()
    venue = os.getenv("VENUE", "unknown").strip()
    structural_gate = os.getenv("STRUCTURAL_GATE", "UNVERIFIED").strip().upper()
    thesis = os.getenv("THESIS", "research signal").strip()

    observed_price = env_float("OBSERVED_PRICE_USD", 0.0)
    liquidity = env_float("LIQUIDITY_USD", 0.0)
    requested = env_float("PAPER_ALLOCATION_USD", 100.0)
    max_slippage_pct = env_float("MAX_SLIPPAGE_PCT", 1.0)
    max_liquidity_share_pct = env_float("MAX_LIQUIDITY_SHARE_PCT", 0.10)

    reasons = []
    if structural_gate != "PASS":
        reasons.append(f"structural gate is {structural_gate}, not PASS")
    if observed_price <= 0:
        reasons.append("observed price must be positive")
    if liquidity <= 0:
        reasons.append("liquidity must be positive")
    if requested <= 0:
        reasons.append("paper allocation must be positive")

    liquidity_cap = liquidity * (max_liquidity_share_pct / 100.0)
    allocation = min(requested, liquidity_cap) if liquidity > 0 else 0.0
    if allocation < requested:
        reasons.append(
            f"requested allocation exceeds {max_liquidity_share_pct:.3f}% liquidity cap"
        )

    # Transparent conservative toy slippage model for paper testing only:
    # impact rises with position/liquidity and is capped by the configured max.
    participation = allocation / liquidity if liquidity > 0 else math.inf
    estimated_slippage_pct = min(max_slippage_pct, participation * 100.0 * 2.0)
    simulated_fill = observed_price * (1.0 + estimated_slippage_pct / 100.0)

    executable = not any(
        r.startswith("structural")
        or r.startswith("observed")
        or r.startswith("liquidity must")
        or r.startswith("paper allocation")
        for r in reasons
    )
    if allocation <= 0:
        executable = False

    # Rules are frozen at signal time so later evaluation cannot use hindsight.
    scale_price = simulated_fill * 1.10
    stop_price = simulated_fill * 0.75
    take_1 = simulated_fill * 2.0
    take_2 = simulated_fill * 4.0

    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "ecosystem": ecosystem,
        "asset": asset,
        "contract": contract,
        "venue": venue,
        "thesis": thesis,
        "structural_gate": structural_gate,
        "observed_price_usd": observed_price,
        "liquidity_usd": liquidity,
        "requested_allocation_usd": requested,
        "allowed_allocation_usd": round(allocation, 2),
        "liquidity_share_pct": round(participation * 100.0, 6) if liquidity > 0 else None,
        "estimated_slippage_pct": round(estimated_slippage_pct, 4),
        "simulated_fill_usd": round(simulated_fill, 12),
        "executable": executable,
        "notes": reasons,
        "frozen_rules": {
            "cancel_entry_if": [
                "structural gate is not PASS",
                "liquidity falls below supplied signal liquidity by 30% before fill",
                "estimated slippage exceeds configured maximum",
            ],
            "scale_only_if": [
                "price persists at or above +10% from initial simulated fill",
                "structural gate remains PASS",
                "liquidity and holder participation do not materially deteriorate",
            ],
            "risk_exit": f"paper exit at -25% ({stop_price:.12g}) or immediate structural-gate failure",
            "take_profit_1": f"paper realize 25% at 2x ({take_1:.12g})",
            "take_profit_2": f"paper realize another 25% at 4x ({take_2:.12g})",
            "remainder": "track until thesis/regime breaks; no hindsight rule changes",
        },
    }

    print(json.dumps(record, indent=2, sort_keys=True))
    compact = json.dumps(record, separators=(",", ":"))
    write_output("executable", str(executable).lower())
    write_output("asset", asset)
    write_output("fill", f"{simulated_fill:.12g}")
    write_output("allocation", f"{allocation:.2f}")
    write_output("record", compact)


if __name__ == "__main__":
    main()
