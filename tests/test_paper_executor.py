import unittest

import paper_executor


class PaperExecutorTests(unittest.TestCase):
    def test_build_execution_record_for_valid_signal(self) -> None:
        record = paper_executor.build_execution_record(
            {
                "signal_timestamp_utc": "2026-09-02T22:34:00Z",
                "ecosystem": "Robinhood Chain",
                "asset": "PONS",
                "contract": "0xabc",
                "venue": "Uniswap v3",
                "observed_price_usd": 0.5,
                "liquidity_usd": 5_000_000,
                "structural_gate": "PASS",
                "paper_allocation_usd": 100,
                "max_slippage_pct": 1.0,
                "max_liquidity_share_pct": 0.10,
                "thesis": "Test thesis",
                "research_evidence": {"market_snapshot": "ok"},
                "signal_file": "signals/example.json",
            }
        )

        self.assertTrue(record["executable"])
        self.assertEqual(record["asset"], "PONS")
        self.assertEqual(record["allowed_allocation_usd"], 100.0)
        self.assertAlmostEqual(record["simulated_fill_usd"], 0.50002, places=8)
        self.assertEqual(record["blocking_reasons"], [])
        self.assertEqual(record["source_signal_timestamp"], "2026-09-02T22:34:00Z")
        self.assertEqual(record["source_signal_file"], "signals/example.json")

    def test_build_execution_record_rejects_invalid_signal(self) -> None:
        with self.assertRaisesRegex(ValueError, "asset must be a non-empty string"):
            paper_executor.build_execution_record(
                {
                    "ecosystem": "Robinhood Chain",
                    "asset": "",
                    "contract": "0xabc",
                    "venue": "Uniswap v3",
                    "observed_price_usd": 0.5,
                    "liquidity_usd": 5_000_000,
                    "structural_gate": "PASS",
                    "paper_allocation_usd": 100,
                    "max_slippage_pct": 1.0,
                    "max_liquidity_share_pct": 0.10,
                    "thesis": "Test thesis",
                }
            )

    def test_build_execution_record_rejects_invalid_risk_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_liquidity_share_pct must be positive"):
            paper_executor.build_execution_record(
                {
                    "ecosystem": "Robinhood Chain",
                    "asset": "PONS",
                    "contract": "0xabc",
                    "venue": "Uniswap v3",
                    "observed_price_usd": 0.5,
                    "liquidity_usd": 5_000_000,
                    "structural_gate": "PASS",
                    "paper_allocation_usd": 100,
                    "max_slippage_pct": 1.0,
                    "max_liquidity_share_pct": 0,
                    "thesis": "Test thesis",
                }
            )

    def test_build_execution_record_rejects_non_positive_numeric_inputs(self) -> None:
        base_signal = {
            "ecosystem": "Robinhood Chain",
            "asset": "PONS",
            "contract": "0xabc",
            "venue": "Uniswap v3",
            "observed_price_usd": 0.5,
            "liquidity_usd": 5_000_000,
            "structural_gate": "PASS",
            "paper_allocation_usd": 100,
            "max_slippage_pct": 1.0,
            "max_liquidity_share_pct": 0.10,
            "thesis": "Test thesis",
        }

        with self.assertRaisesRegex(ValueError, "observed_price_usd must be positive"):
            paper_executor.build_execution_record({**base_signal, "observed_price_usd": 0})

        with self.assertRaisesRegex(ValueError, "liquidity_usd must be positive"):
            paper_executor.build_execution_record({**base_signal, "liquidity_usd": 0})

        with self.assertRaisesRegex(ValueError, "paper_allocation_usd must be positive"):
            paper_executor.build_execution_record({**base_signal, "paper_allocation_usd": 0})

    def test_build_execution_record_rejects_invalid_optional_metadata(self) -> None:
        base_signal = {
            "ecosystem": "Robinhood Chain",
            "asset": "PONS",
            "contract": "0xabc",
            "venue": "Uniswap v3",
            "observed_price_usd": 0.5,
            "liquidity_usd": 5_000_000,
            "structural_gate": "PASS",
            "paper_allocation_usd": 100,
            "max_slippage_pct": 1.0,
            "max_liquidity_share_pct": 0.10,
            "thesis": "Test thesis",
        }

        with self.assertRaisesRegex(ValueError, "signal_timestamp_utc must be a non-empty string"):
            paper_executor.build_execution_record({**base_signal, "signal_timestamp_utc": 123})

        with self.assertRaisesRegex(ValueError, "signal_file must be a non-empty string"):
            paper_executor.build_execution_record({**base_signal, "signal_file": ""})


if __name__ == "__main__":
    unittest.main()
