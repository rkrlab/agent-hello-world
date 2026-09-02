"""Dependency-free Bitcoin price monitor."""

import json
import os
import urllib.request


API_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies=usd"
)


def fetch_bitcoin_price() -> float:
    request = urllib.request.Request(
        API_URL,
        headers={"Accept": "application/json", "User-Agent": "agent-hello-world/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    return float(payload["bitcoin"]["usd"])


def write_github_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"{name}={value}\n")


def main() -> None:
    threshold = float(os.getenv("BTC_ALERT_ABOVE_USD", "150000"))
    force_alert = os.getenv("FORCE_ALERT", "false").lower() == "true"
    price = fetch_bitcoin_price()
    should_alert = force_alert or price >= threshold

    print(f"Bitcoin price: ${price:,.2f}")
    print(f"Alert threshold: ${threshold:,.2f}")
    print(f"Should alert: {should_alert}")

    write_github_output("price", f"{price:.2f}")
    write_github_output("threshold", f"{threshold:.2f}")
    write_github_output("should_alert", str(should_alert).lower())
    write_github_output("forced", str(force_alert).lower())


if __name__ == "__main__":
    main()
