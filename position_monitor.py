"""Monitor frozen paper crypto positions against live DEX data.

Paper-only: never sends transactions or touches wallets.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SEARCH_URL = "https://api.dexscreener.com/latest/dex/search/?q="


def write_output(name: str, value: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def fetch_pair(contract: str, pair_address: str) -> dict:
    url = SEARCH_URL + urllib.parse.quote(contract)
    req = urllib.request.Request(url, headers={"User-Agent": "agent-hello-world/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.load(response)
    wanted = pair_address.lower()
    pairs = payload.get("pairs") or []
    for pair in pairs:
        if str(pair.get("pairAddress", "")).lower() == wanted:
            return pair
    raise RuntimeError(f"Configured pair {pair_address} not found for {contract}")


def evaluate(position: dict, pair: dict) -> dict:
    price = float(pair["priceUsd"])
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
    position_path = Path(os.getenv("POSITION_FILE", "positions/pons.json"))
    with position_path.open("r", encoding="utf-8") as f:
        position = json.load(f)
    pair = fetch_pair(position["contract"], position["pair_address"])
    result = evaluate(position, pair)
    print(json.dumps(result, indent=2, sort_keys=True))
    write_output("issue_number", str(result["issue_number"]))
    write_output("asset", result["asset"])
    write_output("state", result["state"])
    write_output("price", f'{result["price_usd"]:.12g}')
    write_output("return_pct", f'{result["return_pct"]:.4f}')
    write_output("liquidity", f'{result["liquidity_usd"]:.2f}')
    write_output("record", json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
