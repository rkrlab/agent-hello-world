import copy
import json
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import refresh_valuation as valuation


class ValuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = json.loads((valuation.ROOT / "state.json").read_text())
        cls.ledger = [json.loads(line, parse_float=Decimal) for line in
                      (valuation.ROOT / "trades.jsonl").read_text().splitlines()]
        cls.initial = json.loads((valuation.ROOT / valuation.INITIAL).read_text(),
                                 parse_float=Decimal)

    def setUp(self):
        self.now = valuation.timestamp(self.state["last_full_mark_at_utc"]) + timedelta(hours=1)
        self.assets = sorted(self.state["positions"].keys() | self.state["benchmark"]["quantities"].keys())
        self.marks = {asset: valuation.Mark(Decimal("100"), self.now, "test fixture")
                      for asset in self.assets}

    def test_reconciles_repository_ledger(self):
        valuation.reconcile(self.state, self.ledger, self.initial)

    def test_detects_state_or_ledger_divergence(self):
        for field in ("current_cash_usd", "realized_pnl_usd", "trade_count"):
            with self.subTest(field=field):
                changed = {**self.state, field: self.state[field] + 1}
                with self.assertRaises(ValueError):
                    valuation.reconcile(changed, self.ledger, self.initial)
        with self.assertRaises(ValueError):
            valuation.reconcile(self.state, self.ledger[:-1], self.initial)

    def test_rejects_duplicate_execution_and_changed_fee(self):
        duplicate = self.ledger + [self.ledger[-1]]
        with self.assertRaisesRegex(ValueError, "Invalid ledger order"):
            valuation.reconcile(self.state, duplicate, self.initial)
        changed = copy.deepcopy(self.ledger)
        changed[-1]["transaction_cost_usd"] += 1
        with self.assertRaisesRegex(ValueError, "fee"):
            valuation.reconcile(self.state, changed, self.initial)

    def test_valuation_math_and_preserved_accounting(self):
        updated = valuation.revalue(self.state, self.marks, self.now)
        positions = self.state["positions"]
        nav = self.state["current_cash_usd"] + sum(pos["quantity"] * 100 for pos in positions.values())
        passive = self.state["benchmark"]["cash_usd"] + sum(
            qty * 100 for qty in self.state["benchmark"]["quantities"].values())
        self.assertAlmostEqual(updated["current_nav_usd"], nav)
        self.assertAlmostEqual(updated["benchmark_nav_usd"], passive)
        self.assertAlmostEqual(updated["alpha_vs_benchmark_usd"], nav - passive)
        self.assertAlmostEqual(updated["alpha_vs_benchmark_bps"], (nav - passive) / passive * 10000)
        self.assertAlmostEqual(updated["total_unrealized_pnl_usd"], sum(
            pos["quantity"] * 100 - pos["total_cost_basis_usd"] for pos in positions.values()))
        for asset, pos in positions.items():
            marked = updated["positions"][asset]
            self.assertAlmostEqual(marked["marked_value_usd"], pos["quantity"] * 100)
            self.assertAlmostEqual(marked["portfolio_weight_pct"], pos["quantity"] * 100 / nav * 100)
            self.assertEqual(marked["current_mark_at_utc"], valuation.utc(self.now))
            for key in ("quantity", "average_cost_usd", "total_cost_basis_usd",
                        "realized_pnl_usd", "latest_trade_id", "signal_id"):
                self.assertEqual(marked[key], pos[key])
        for field in ("current_cash_usd", "realized_pnl_usd", "trade_count", "last_trade_id", "benchmark"):
            self.assertEqual(updated[field], self.state[field])

    def test_requires_benchmark_only_price_and_keeps_its_provenance(self):
        state = copy.deepcopy(self.state)
        asset, pos = next(iter(state["positions"].items()))
        del state["positions"][asset]
        state["benchmark"]["quantities"][asset] = pos["quantity"]
        state["current_cash_usd"] += pos["total_cost_basis_usd"]
        without_asset = {a: mark for a, mark in self.marks.items() if a != asset}
        with self.assertRaisesRegex(ValueError, "Missing quotes"):
            valuation.revalue(state, without_asset, self.now)
        updated = valuation.revalue(state, self.marks, self.now)
        saved = updated["last_recorded_portfolio_mark"]["benchmark_only_marks"]
        self.assertEqual(saved[asset], valuation.mark_fields(self.marks[asset]))

    def test_rejects_invalid_stale_future_and_widely_spaced_prices(self):
        asset = self.assets[0]
        cases = [
            valuation.Mark(Decimal("0"), self.now, "fixture"),
            valuation.Mark(Decimal("NaN"), self.now, "fixture"),
            self.marks[asset]._replace(timestamp=self.now - timedelta(minutes=6)),
            self.marks[asset]._replace(timestamp=self.now + timedelta(seconds=1)),
            self.marks[asset]._replace(timestamp=self.now - timedelta(minutes=3)),
        ]
        for mark in cases:
            with self.subTest(mark=mark):
                with self.assertRaises(ValueError):
                    valuation.validate_marks(self.assets, {**self.marks, asset: mark}, self.now)

    def test_fallback_uses_one_complete_provider_batch(self):
        with patch.object(valuation, "gecko_marks", side_effect=KeyError("missing")), \
             patch.object(valuation, "paprika_marks", return_value=self.marks), \
             patch.object(valuation, "datetime", wraps=valuation.datetime) as clock:
            clock.now.return_value = self.now
            actual, fetched = valuation.live_marks(self.assets)
        self.assertEqual(actual, self.marks)
        self.assertEqual(fetched, self.now)

    def test_rejects_quote_older_than_saved_mark(self):
        asset = next(iter(self.state["positions"]))
        state = copy.deepcopy(self.state)
        state["positions"][asset]["current_mark_at_utc"] = valuation.utc(self.now)
        older = self.marks[asset]._replace(timestamp=self.now - timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, "quote predates saved mark"):
            valuation.revalue(state, {**self.marks, asset: older}, self.now)

    def test_only_successful_batch_writes_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("state.json", "trades.jsonl", valuation.INITIAL):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes((valuation.ROOT / name).read_bytes())
            original_state = (root / "state.json").read_bytes()
            original_ledger = (root / "trades.jsonl").read_bytes()
            with patch.object(valuation, "ROOT", root), patch("sys.argv", ["refresh", "--write"]), \
                 patch.object(valuation, "gecko_marks", return_value={}), \
                 patch.object(valuation, "paprika_marks", return_value={}):
                with self.assertRaisesRegex(ValueError, "No complete fresh quote batch"):
                    valuation.main()
            self.assertEqual((root / "state.json").read_bytes(), original_state)
            self.assertEqual((root / "trades.jsonl").read_bytes(), original_ledger)

            with patch.object(valuation, "ROOT", root), patch("sys.argv", ["refresh", "--write"]), \
                 patch.object(valuation, "live_marks", return_value=(self.marks, self.now)):
                valuation.main()
            updated = json.loads((root / "state.json").read_text())
            self.assertEqual(updated["last_full_mark_at_utc"], valuation.utc(self.now))
            self.assertEqual((root / "trades.jsonl").read_bytes(), original_ledger)


if __name__ == "__main__":
    unittest.main()
