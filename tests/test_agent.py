import unittest
from unittest import mock

import agent


class AgentTests(unittest.TestCase):
    def test_fetch_pons_price_uses_configured_pair(self) -> None:
        payload = {
            "pairs": [
                {"pairAddress": "0xother", "priceUsd": "0.2"},
                {"pairAddress": "0x10CC6BD38112cAc182db90B6a71d8Bb5939526bA", "priceUsd": "1.23"},
            ]
        }
        with mock.patch("agent.request_json", return_value=payload):
            price = agent.fetch_pons_price()

        self.assertEqual(price, 1.23)

    def test_main_writes_outputs_for_pons_monitor(self) -> None:
        with (
            mock.patch("agent.fetch_pons_price", return_value=1.5),
            mock.patch("agent.write_github_output") as write_output,
            mock.patch.dict("os.environ", {"PONS_ALERT_ABOVE_USD": "1", "FORCE_ALERT": "false"}, clear=False),
        ):
            agent.main()

        calls = {call.args[0]: call.args[1] for call in write_output.call_args_list}
        self.assertEqual(calls["price"], "1.500000")
        self.assertEqual(calls["threshold"], "1.000000")
        self.assertEqual(calls["should_alert"], "true")
        self.assertEqual(calls["forced"], "false")


if __name__ == "__main__":
    unittest.main()
