"""Deterministic paper-execution engine for crypto research signals.

This module NEVER sends a transaction or touches a wallet. It converts a research
signal into an auditable simulated execution plan and emits GitHub Actions outputs.
"""

import json
import math
import os
from datetime import datetime, timezone

from workflow_utils import (
    load_json_file,
    require_float,
    require_mapping,
    require_string,
    write_github_output,
)


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def load_signal() -> dict:
    signal_file = os.getenv("SIGNAL_FILE", "").strip()
    if signal_file:
        data = load_json_file(signal_file, label="Signal")
        data["signal_file"] = signal_file
        return data

    return {
        "ecosystem": os.getenv("ECOSYSTEM", "unknown"),
        "asset": os.getenv("ASSET", "UNKNOWN"),
        "contract": os.getenv("CONTRACT", "unknown"),
        "venue": os.getenv("VENUE", "unknown"),
        "observed_price_usd": env_float("OBSERVED_PRICE_USD", 0.0),
        "liquidity_usd": env_float("LIQUIDITY_USD", 0.0),
        "structural_gate": os.getenv("STRUCTURAL_GATE", "UNVERIFIED"),
        "paper_allocation_usd": env_float("PAPER_ALLOCATION_USD", 100.0),
        "max_slippage_pct": env_float("MAX_SLIPPAGE_PCT", 1.0),
        "max_liquidity_share_pct": env_float("MAX_LIQUIDITY_SHARE_PCT", 0.10),
        "thesis": os.getenv("THESIS", "research signal"),
    }


def validate_signal(signal: dict) -> dict:
    signal_timestamp = signal.get("signal_timestamp_utc")
    if signal_timestamp is not None:
        if not isinstance(signal_timestamp, str) or not signal_timestamp.strip():
            raise ValueError("signal_timestamp_utc must be a non-empty string when provided")
        signal_timestamp = signal_timestamp.strip()

    signal_file = signal.get("signal_file")
    if signal_file is not None:
        if not isinstance(signal_file, str) or not signal_file.strip():
            raise ValueError("signal_file must be a non-empty string when provided")
        signal_file = signal_file.strip()

    validated = {
        "ecosystem": require_string(signal, "ecosystem"),
        "asset": require_string(signal, "asset"),
        "contract": require_string(signal, "contract"),
        "venue": require_string(signal, "venue"),
        "observed_price_usd": require_float(signal, "observed_price_usd"),
        "liquidity_usd": require_float(signal, "liquidity_usd"),
        "structural_gate": require_string(signal, "structural_gate").upper(),
        "paper_allocation_usd": require_float(signal, "paper_allocation_usd"),
        "max_slippage_pct": require_float(signal, "max_slippage_pct"),
        "max_liquidity_share_pct": require_float(signal, "max_liquidity_share_pct"),
        "thesis": require_string(signal, "thesis"),
        "research_evidence": require_mapping(signal, "research_evidence", default={}),
        "signal_timestamp_utc": signal_timestamp,
        "signal_file": signal_file,
    }
    if validated["max_slippage_pct"] < 0:
        raise ValueError("max_slippage_pct must be zero or positive")
    if validated["max_liquidity_share_pct"] <= 0:
        raise ValueError("max_liquidity_share_pct must be positive")
    if validated["observed_price_usd"] <= 0:
        raise ValueError("observed_price_usd must be positive")
    if validated["liquidity_usd"] <= 0:
        raise ValueError("liquidity_usd must be positive")
    if validated["paper_allocation_usd"] <= 0:
        raise ValueError("paper_allocation_usd must be positive")
    return validated


def build_execution_record(signal: dict) -> dict:
    s = validate_signal(signal)
    asset = s["asset"]
    contract = s["contract"]
    ecosystem = s["ecosystem"]
    venue = s["venue"]
    structural_gate = s["structural_gate"]
    thesis = s["thesis"]

    observed_price = s["observed_price_usd"]
    liquidity = s["liquidity_usd"]
    requested = s["paper_allocation_usd"]
    max_slippage_pct = s["max_slippage_pct"]
    max_liquidity_share_pct = s["max_liquidity_share_pct"]

    blocking = []
    notes = []
    if structural_gate != "PASS":
        blocking.append(f"structural gate is {structural_gate}, not PASS")
    if observed_price <= 0:
        blocking.append("observed price must be positive")
    if liquidity <= 0:
        blocking.append("liquidity must be positive")
    if requested <= 0:
        blocking.append("paper allocation must be positive")

    liquidity_cap = liquidity * (max_liquidity_share_pct / 100.0)
    allocation = min(requested, liquidity_cap) if liquidity > 0 else 0.0
    if allocation < requested:
        notes.append(
            f"requested allocation capped at {max_liquidity_share_pct:.3f}% of supplied liquidity"
        )

    participation = allocation / liquidity if liquidity > 0 else math.inf
    estimated_slippage_pct = min(max_slippage_pct, participation * 100.0 * 2.0)
    simulated_fill = observed_price * (1.0 + estimated_slippage_pct / 100.0)
    executable = not blocking and allocation > 0

    scale_price = simulated_fill * 1.10
    stop_price = simulated_fill * 0.75
    take_1 = simulated_fill * 2.0
    take_2 = simulated_fill * 4.0

    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_signal_timestamp": s.get("signal_timestamp_utc"),
        "source_signal_file": s.get("signal_file"),
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
        "blocking_reasons": blocking,
        "notes": notes,
        "research_evidence": s["research_evidence"],
        "frozen_rules": {
            "cancel_entry_if": [
                "structural gate is not PASS",
                "liquidity falls 30% from supplied signal liquidity before fill",
                "estimated slippage exceeds configured maximum",
            ],
            "scale_only_if": [
                f"price persists at or above +10% from initial simulated fill ({scale_price:.12g})",
                "structural gate remains PASS",
                "liquidity and holder participation do not materially deteriorate",
            ],
            "risk_exit": f"paper exit at -25% ({stop_price:.12g}) or immediate structural-gate failure",
            "take_profit_1": f"paper realize 25% at 2x ({take_1:.12g})",
            "take_profit_2": f"paper realize another 25% at 4x ({take_2:.12g})",
            "remainder": "track until thesis/regime breaks; no hindsight rule changes",
        },
    }
    return record


def main() -> None:
    try:
        record = build_execution_record(load_signal())

        print(json.dumps(record, indent=2, sort_keys=True))
        compact = json.dumps(record, separators=(",", ":"))
        write_github_output("executable", str(record["executable"]).lower())
        write_github_output("asset", record["asset"])
        write_github_output("fill", f'{record["simulated_fill_usd"]:.12g}')
        write_github_output("allocation", f'{record["allowed_allocation_usd"]:.2f}')
        write_github_output("record", compact)
    except Exception as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
