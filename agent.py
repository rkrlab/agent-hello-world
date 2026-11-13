"""Dependency-free PONS price monitor."""

import os
import urllib.parse

from workflow_utils import request_json, write_github_output


SEARCH_URL = "https://api.dexscreener.com/latest/dex/search/?q="
DEFAULT_ASSET = "PONS"
DEFAULT_CONTRACT = "0x39dBED3a2bd333467115dE45665cC57F813C4571"
DEFAULT_PAIR_ADDRESS = "0x10CC6BD38112cAc182db90B6a71d8Bb5939526bA"


def fetch_pons_price() -> float:
    contract = os.getenv("PONS_CONTRACT", DEFAULT_CONTRACT)
    pair_address = os.getenv("PONS_PAIR_ADDRESS", DEFAULT_PAIR_ADDRESS).lower()
    payload = request_json(SEARCH_URL + urllib.parse.quote(contract))
    for pair in payload.get("pairs") or []:
        if str(pair.get("pairAddress", "")).lower() == pair_address:
            return float(pair["priceUsd"])
    raise RuntimeError(f"Configured PONS pair {pair_address} not found for {contract}")


def main() -> None:
    asset = os.getenv("ALERT_ASSET", DEFAULT_ASSET)
    threshold = float(os.getenv("PONS_ALERT_ABOVE_USD", "1"))
    force_alert = os.getenv("FORCE_ALERT", "false").lower() == "true"
    price = fetch_pons_price()
    should_alert = force_alert or price >= threshold

    print(f"{asset} price: ${price:,.6f}")
    print(f"Alert threshold: ${threshold:,.2f}")
    print(f"Should alert: {should_alert}")

    write_github_output("price", f"{price:.6f}")
    write_github_output("threshold", f"{threshold:.6f}")
    write_github_output("should_alert", str(should_alert).lower())
    write_github_output("forced", str(force_alert).lower())

if __name__ == "__main__":
    main()
