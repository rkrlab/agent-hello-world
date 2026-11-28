"""Monitor frozen paper crypto positions against live DEX data.

Paper-only: never sends transactions or touches wallets.
"""

import json
import os
import urllib.parse
from datetime import datetime, timezone

from workflow_utils import (
    load_json_file,
    request_json,
    require_float,
    require_int,
    require_mapping,
    require_string,
    write_github_output,
)


SEARCH_URL = "https://api.dexscreener.com/latest/dex/search/?q="

def fetch_pair(contract: str, pair_address: str) -> dict:
    url = SEARCH_URL + urllib.parse.quote(contract)
    payload = request_json(url)
    wanted = pair_address.lower()
    pairs = payload.get("pairs") or []
    if not isinstance(pairs, list):
        raise RuntimeError("DexScreener response did not include a valid pairs list")
    for pair in pairs:
        if str(pair.get("pairAddress", "")).lower() == wanted:
            return pair
    raise RuntimeError(f"Configured pair {pair_address} not found for {contract}")


def validate_position(position: dict) -> dict:
    validated = {
        "issue_number": require_int(position, "issue_number"),
        "asset": require_string(position, "asset"),
        "contract": require_string(position, "contract"),
        "pair_address": require_string(position, "pair_address"),
        "entry_fill_usd": require_float(position, "entry_fill_usd"),
        "entry_liquidity_usd": require_float(position, "entry_liquidity_usd"),
        "scale_price_usd": require_float(position, "scale_price_usd"),
        "stop_price_usd": require_float(position, "stop_price_usd"),
        "take_profit_1_usd": require_float(position, "take_profit_1_usd"),
        "take_profit_2_usd": require_float(position, "take_profit_2_usd"),
        "structural_gate": require_string(position, "structural_gate").upper(),
    }
    if validated["entry_fill_usd"] <= 0:
        raise ValueError("entry_fill_usd must be positive")
    if validated["entry_liquidity_usd"] <= 0:
        raise ValueError("entry_liquidity_usd must be positive")
    return validated


def evaluate(position: dict, pair: dict) -> dict:
    position = validate_position(position)
    try:
        price = float(pair["priceUsd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("pair priceUsd must be a number") from exc
    liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
    entry = float(position["entry_fill_usd"])
    ret_pct = (price / entry - 1.0) * 100.0

    if position.get("structural_gate") != "PASS":
        state = "STRUCTURAL_FAIL"
    elif price <= float(position["stop_price_usd"]):
        state = "STOP"
    elif price >= float(position["take_profit_2_usd"]):
        state = "TP2"
    elif price >= float(position["take_profit_1_usd"]):
        state = "TP1"
    elif price >= float(position["scale_price_usd"]):
        state = "SCALE_READY"
    else:
        state = "HOLD"

    if liquidity < float(position["entry_liquidity_usd"]) * 0.70 and state not in {"STOP", "STRUCTURAL_FAIL"}:
        state = "LIQUIDITY_WARNING"

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "PAPER_ONLY",
        "issue_number": int(position["issue_number"]),
        "asset": position["asset"],
        "contract": position["contract"],
        "pair_address": position["pair_address"],
        "state": state,
        "price_usd": price,
        "entry_fill_usd": entry,
        "return_pct": round(ret_pct, 4),
        "liquidity_usd": liquidity,
        "entry_liquidity_usd": float(position["entry_liquidity_usd"]),
        "volume_24h_usd": float((pair.get("volume") or {}).get("h24") or 0),
        "txns_24h": pair.get("txns", {}).get("h24", {}),
        "thresholds": {
            "scale": float(position["scale_price_usd"]),
            "stop": float(position["stop_price_usd"]),
            "tp1": float(position["take_profit_1_usd"]),
            "tp2": float(position["take_profit_2_usd"]),
        },
    }


def main() -> None:
    try:
        position_path = os.getenv("POSITION_FILE", "positions/pons.json")
        position = validate_position(load_json_file(position_path, label="Position"))
        pair = fetch_pair(position["contract"], position["pair_address"])
        result = evaluate(position, pair)
        print(json.dumps(result, indent=2, sort_keys=True))
        write_github_output("issue_number", str(result["issue_number"]))
        write_github_output("asset", result["asset"])
        write_github_output("state", result["state"])
        write_github_output("price", f'{result["price_usd"]:.12g}')
        write_github_output("return_pct", f'{result["return_pct"]:.4f}')
        write_github_output("liquidity", f'{result["liquidity_usd"]:.2f}')
        write_github_output("record", json.dumps(result, separators=(",", ":")))
    except Exception as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
