"""Unit tests for CX-to-CRM Promo Guard & Proactive Recovery Engine."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import cx_io as cio  # noqa: E402
import cx_promo_guard as guard  # noqa: E402
import web_app  # noqa: E402

FIX = ROOT / "fixtures"


class TestCrossToolPromoGuard(unittest.TestCase):
    def setUp(self):
        self.res = guard.run_cx_guard(
            shipments_path=FIX / "shipments_carrier_schema.csv",
            reviews_path=FIX / "trustpilot_reviews_schema.csv",
            tickets_path=FIX / "zendesk_tickets_schema.csv",
            orders_path=FIX / "shopify_orders_schema.csv",
            as_of=date(2026, 6, 1),
        )
        self.klaviyo_map = {r[0]: r for r in self.res["klaviyo_rows"]}

    def test_resolves_missing_emails_via_shopify_and_deduplicates_vip_at_p0(self):
        # Order #3003 has NO email in shipments or Trustpilot, resolved to vip.stuck@example.com via Shopify!
        self.assertIn("vip.stuck@example.com", self.klaviyo_map)
        row = self.klaviyo_map["vip.stuck@example.com"]
        self.assertEqual(row[1], "true")  # cx_promo_hold
        self.assertEqual(row[2], "true")  # cx_review_request_hold
        self.assertEqual(row[3], "HOLD")
        self.assertIn("carrier_exception", row[4])
        self.assertIn("negative_review_1star", row[4])
        self.assertIn("open_ticket_urgent", row[4])
        self.assertEqual(row[9], "P0")

        # Must sit #1 in the deduplicated CS recovery queue as VIP P0 (LTV 585)
        top = self.res["queue_rows"][0]
        self.assertEqual(top[0], "P0")
        self.assertEqual(top[2], "vip.stuck@example.com")
        self.assertEqual(top[3], "yes")
        self.assertAlmostEqual(top[4], 585.00)

    def test_emits_release_when_late_delivery_and_ticket_cleared(self):
        # #3006 delivered late on May 10 (>7d cooldown before June 1) and Zendesk ticket is solved -> RELEASE!
        rel = self.klaviyo_map["resolved.old@example.com"]
        self.assertEqual(rel[1], "false")
        self.assertEqual(rel[3], "RELEASE")

    def test_holds_recent_late_delivery_and_open_zendesk_ticket(self):
        self.assertEqual(self.klaviyo_map["recent.late@example.com"][3], "HOLD")
        self.assertIn("delivered_late_recent", self.klaviyo_map["recent.late@example.com"][4])
        self.assertEqual(self.klaviyo_map["ticket.only@example.com"][3], "HOLD")
        self.assertEqual(self.klaviyo_map["zendesk.angry@example.com"][3], "HOLD")
        # Happy on-time 5-star customer must NOT be suppressed
        self.assertNotIn("happy.ontime@example.com", self.klaviyo_map)

    def test_carrier_sla_scorecard_tracks_delays_exceptions_and_linked_reviews(self):
        by_carrier = {r[0]: r for r in self.res["carrier_rows"]}
        # BRT: 2 shipments (#3003 exception + 1* review, #3006 delivered late)
        self.assertEqual(by_carrier["BRT"][5], 1)  # exceptions
        self.assertEqual(by_carrier["BRT"][8], 1)  # linked negative reviews
        # GLS: 2 shipments (#3004 still late open + 2* review, #3005 late delivered) -> 100% late rate
        self.assertEqual(by_carrier["GLS"][6], 100.0)
        self.assertEqual(by_carrier["GLS"][8], 1)
        # DHL: 2 delivered on time -> 0% late
        self.assertEqual(by_carrier["DHL"][6], 0.0)


class TestHubSpotTicketsAndBridge(unittest.TestCase):
    def test_reads_native_hubspot_service_hub_tickets(self):
        res = guard.run_cx_guard(
            tickets_path=FIX / "hubspot_tickets_schema.csv",
            as_of=date(2026, 6, 1),
        )
        self.assertEqual(res["summary"]["sources"]["tickets"], "hubspot_tickets")
        km = {r[0]: r for r in res["klaviyo_rows"]}
        self.assertEqual(km["vip.stuck@example.com"][3], "HOLD")
        self.assertEqual(km["resolved.old@example.com"][3], "RELEASE")

    def test_cli_writes_all_operational_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            code = guard.main([
                "--shipments", str(FIX / "shipments_carrier_schema.csv"),
                "--reviews", str(FIX / "trustpilot_reviews_schema.csv"),
                "--tickets", str(FIX / "zendesk_tickets_schema.csv"),
                "--orders", str(FIX / "shopify_orders_schema.csv"),
                "--as-of", "2026-06-01",
                "--out", str(out_dir),
            ])
            self.assertEqual(code, 0)
            for fname in (
                "klaviyo_cx_promo_hold.csv",
                "hubspot_cx_promo_hold.csv",
                "cs_recovery_queue.csv",
                "carrier_sla_scorecard.csv",
                "cx_guard_summary.json",
                "cx_ops_report.html",
            ):
                self.assertTrue((out_dir / fname).exists(), fname)

    def test_browser_bridge_and_formula_neutralization(self):
        out = json.loads(web_app.run_guard(
            str(FIX / "shipments_carrier_schema.csv"),
            str(FIX / "trustpilot_reviews_schema.csv"),
            str(FIX / "zendesk_tickets_schema.csv"),
            str(FIX / "shopify_orders_schema.csv"),
            "2026-06-01",
        ))
        self.assertEqual(out["summary"]["active_crm_promo_holds"], 5)
        self.assertTrue(out["klaviyo_hold_csv"].startswith("Email,cx_promo_hold,"))
        self.assertTrue(out["hubspot_hold_csv"].startswith("Email,CX Promo Hold,"))
        self.assertEqual(cio.safe_cell("=CMD()"), "'=CMD()")


if __name__ == "__main__":
    unittest.main()
