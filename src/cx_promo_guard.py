"""CX-to-CRM Promo Guard & Proactive Recovery Engine.

Bridges the operational gap between Post-Purchase Silos (Shipping/Carriers,
Trustpilot/Reviews, Zendesk/HubSpot Support) and Marketing Automation (Klaviyo,
HubSpot CRM):

1. Cross-tool customer join: links shipments, 1-2 star reviews, and open support
   tickets to customer email (using Shopify Orders to resolve order_id -> email
   and enrich VIP / LTV priority).
2. Automatic CRM Promo & Review-Request Hold: generates ready-to-import CSVs
   for Klaviyo and HubSpot (`cx_promo_hold=true`, `cx_review_request_hold=true`)
   so angry customers or people waiting on a delayed/stuck parcel NEVER receive
   promotional DEM blasts or automated review requests — and releases holds
   (`false`) once delivery/ticket issues clear.
3. Deduplicated, LTV-weighted Customer Service Recovery Queue (`P0`..`P3`):
   merges overlapping shipment + review + ticket issues for the same customer
   into one prioritized ticket assigned to the right owner team.
4. Carrier SLA Scorecard: tracks late rate, open delays, exceptions, average
   delay days, and linked negative reviews per carrier (BI-ready).

Pure Python standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from html import escape
from pathlib import Path

import cx_io as cio

# Auditable multilingual keyword rules for review/ticket routing (no black-box ML).
THEMES: dict[str, tuple[int, str, list[str]]] = {
    "not_received": (
        1,
        "logistics + customer_service",
        [
            "not received", "never arrived", "never received", "didn't arrive", "missing item", "lost parcel",
            "non ricevuto", "non ho ricevuto", "mai arrivato", "non è arrivato", "non e arrivato", "mancante",
            "no recibido", "nunca llegó", "jamais reçu", "non reçu",
        ],
    ),
    "product_quality": (
        2,
        "product / quality",
        [
            "broken", "damaged", "defect", "defective", "doesn't work", "not working", "wrong item", "leaking",
            "rotto", "danneggiat", "difett", "non funziona", "sbagliat",
            "roto", "dañado", "cassé", "endommagé",
        ],
    ),
    "delivery_delay": (
        3,
        "logistics",
        [
            "delivery", "late", "delay", "shipping", "courier", "parcel", "stuck", "tracking",
            "consegna", "ritardo", "spedizione", "corriere", "pacco", "bloccato",
            "retraso", "envío", "retard", "livraison",
        ],
    ),
    "customer_service": (
        3,
        "customer_service",
        [
            "customer service", "support", "refund", "no reply", "no response", "exchange", "return",
            "assistenza", "nessuna risposta", "rimborso", "reso", "servizio clienti",
            "reembolso", "soporte", "remboursement",
        ],
    ),
}

KLAVIYO_HOLD_HEADER = [
    "Email",
    "cx_promo_hold",
    "cx_review_request_hold",
    "cx_hold_action",
    "cx_hold_reason",
    "cx_hold_until",
    "cx_active_order_id",
    "cx_active_carrier",
    "cx_days_late",
    "cx_priority_tier",
]
HUBSPOT_HOLD_HEADER = [
    "Email",
    "CX Promo Hold",
    "CX Review Request Hold",
    "CX Hold Action",
    "CX Hold Reason",
    "CX Hold Until",
    "Active Order ID",
    "Active Carrier",
    "Priority Tier",
]
QUEUE_HEADER = [
    "priority_tier",
    "owner_team",
    "email",
    "is_vip",
    "customer_ltv",
    "order_id",
    "carrier",
    "days_late",
    "signals",
    "theme",
    "excerpt",
]
CARRIER_HEADER = [
    "carrier",
    "total_shipments",
    "delivered",
    "late_delivered",
    "still_late_open",
    "exceptions",
    "late_rate_pct",
    "avg_days_late",
    "linked_negative_reviews",
]


def classify_text(text: str) -> tuple[str, int, str]:
    low = (text or "").lower()
    hits = [(urg, owner, theme) for theme, (urg, owner, kws) in THEMES.items() if any(k in low for k in kws)]
    if not hits:
        return "general_issue", 4, "customer_service"
    hits.sort(key=lambda x: x[0])
    urg, owner, theme = hits[0]
    return theme, urg, owner


def run_cx_guard(
    *,
    shipments_path: Path | None = None,
    reviews_path: Path | None = None,
    tickets_path: Path | None = None,
    orders_path: Path | None = None,
    as_of: date | None = None,
    late_delivery_cooldown_days: int = 7,
    review_hold_days: int = 30,
    max_negative_rating: float = 2.0,
    default_sla_days: int = 5,
    vip_min_orders: int = 3,
    vip_min_spend: float = 300.0,
) -> dict:
    if not any((shipments_path, reviews_path, tickets_path)):
        raise ValueError("Provide at least one CX source CSV: shipments, reviews, or support tickets.")

    ref_day = as_of or date.today()
    order_to_email: dict[str, str] = {}
    ltv_by_email: dict[str, dict] = {}
    sources: dict[str, str | None] = {"orders": None, "shipments": None, "reviews": None, "tickets": None}

    if orders_path is not None:
        order_to_email, ltv_by_email = cio.read_shopify_orders_context(
            orders_path, vip_min_orders=vip_min_orders, vip_min_spend=vip_min_spend
        )
        sources["orders"] = "shopify_orders"

    shipments: list[dict] = []
    if shipments_path is not None:
        sources["shipments"], shipments = cio.read_shipments(
            shipments_path, order_to_email=order_to_email, default_sla_days=default_sla_days
        )

    reviews: list[dict] = []
    if reviews_path is not None:
        sources["reviews"], reviews = cio.read_reviews(reviews_path, order_to_email=order_to_email)

    tickets: list[dict] = []
    if tickets_path is not None:
        sources["tickets"], tickets = cio.read_tickets(tickets_path, order_to_email=order_to_email)

    # Order -> carrier map so negative reviews can be attributed back to carriers.
    order_carrier: dict[str, str] = {s["order_key"]: s["carrier"] for s in shipments if s["order_key"]}

    # Per-customer unified state keyed by email (falls back to order:<id> if no email exists).
    customers: dict[str, dict] = {}
    resolved_via_shopify = 0

    def get_cust(email: str, order_id: str = "") -> dict:
        key = email or f"unresolved_order:{order_id}"
        return customers.setdefault(
            key,
            {
                "email": email,
                "order_id": order_id,
                "carrier": "",
                "days_late": 0,
                "hold_reasons": [],
                "release_eligible": False,
                "hold_until": None,
                "urgency": 9,
                "owner_team": "customer_service",
                "theme": "",
                "excerpts": [],
            },
        )

    # 1. Process shipments & carrier scorecard stats
    carrier_stats: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "delivered": 0, "late_delivered": 0, "still_late_open": 0, "exceptions": 0, "delay_sum": 0, "delay_n": 0, "neg_reviews": 0}
    )

    for s in shipments:
        cs = carrier_stats[s["carrier"]]
        cs["total"] += 1
        if s["is_exception"]:
            cs["exceptions"] += 1
        if s["email"] and s["order_key"] in order_to_email:
            resolved_via_shopify += 1

        if not s["is_delivered"]:
            days_late = max(0, (ref_day - s["promised"]).days) if s["promised"] and s["promised"] < ref_day else 0
            if s["is_exception"] or days_late > 0:
                if days_late > 0:
                    cs["still_late_open"] += 1
                    cs["delay_sum"] += days_late
                    cs["delay_n"] += 1
                c = get_cust(s["email"], s["order_id"])
                c["order_id"] = c["order_id"] or s["order_id"]
                c["carrier"] = c["carrier"] or s["carrier"]
                c["days_late"] = max(c["days_late"], days_late)
                reason = "carrier_exception" if s["is_exception"] else "late_in_transit"
                if reason not in c["hold_reasons"]:
                    c["hold_reasons"].append(reason)
                c["hold_until"] = max(c["hold_until"], ref_day + timedelta(days=14)) if c["hold_until"] else (ref_day + timedelta(days=14))
                c["urgency"] = min(c["urgency"], 1 if (s["is_exception"] or days_late >= 4) else 2)
                c["owner_team"] = "logistics + customer_service" if s["is_exception"] else "logistics"
                c["theme"] = c["theme"] or ("not_received" if s["is_exception"] else "delivery_delay")
                c["excerpts"].append(f"Order {s['order_id']} ({s['carrier']}): {s['status']}, {days_late}d past promise")
        else:
            cs["delivered"] += 1
            days_late = (s["delivered"] - s["promised"]).days if (s["delivered"] and s["promised"] and s["delivered"] > s["promised"]) else 0
            if days_late > 0:
                cs["late_delivered"] += 1
                cs["delay_sum"] += days_late
                cs["delay_n"] += 1
                since_deliv = (ref_day - s["delivered"]).days if s["delivered"] else 999
                c = get_cust(s["email"], s["order_id"])
                c["order_id"] = c["order_id"] or s["order_id"]
                c["carrier"] = c["carrier"] or s["carrier"]
                c["days_late"] = max(c["days_late"], days_late)
                if 0 <= since_deliv <= late_delivery_cooldown_days:
                    if "delivered_late_recent" not in c["hold_reasons"]:
                        c["hold_reasons"].append("delivered_late_recent")
                    until = s["delivered"] + timedelta(days=late_delivery_cooldown_days)
                    c["hold_until"] = max(c["hold_until"], until) if c["hold_until"] else until
                    c["urgency"] = min(c["urgency"], 3)
                    c["theme"] = c["theme"] or "delivery_delay"
                    c["excerpts"].append(f"Order {s['order_id']} ({s['carrier']}): delivered {days_late}d late")
                else:
                    # Previously late, now past cooldown -> emit explicit CRM release signal if no other issues!
                    c["release_eligible"] = True

    # 2. Process negative reviews
    neg_reviews_count = 0
    for rev in reviews:
        if rev["rating"] > max_negative_rating:
            continue
        if rev["date"] and (ref_day - rev["date"]).days > review_hold_days:
            continue
        neg_reviews_count += 1
        carrier = order_carrier.get(rev["order_key"], "")
        if carrier:
            carrier_stats[carrier]["neg_reviews"] += 1
        theme, urg, owner = classify_text(rev["text"])
        c = get_cust(rev["email"], rev["order_id"])
        c["order_id"] = c["order_id"] or rev["order_id"]
        c["carrier"] = c["carrier"] or carrier
        reason = f"negative_review_{int(rev['rating'])}star"
        if reason not in c["hold_reasons"]:
            c["hold_reasons"].append(reason)
        until = (rev["date"] or ref_day) + timedelta(days=review_hold_days)
        c["hold_until"] = max(c["hold_until"], until) if c["hold_until"] else until
        if urg < c["urgency"]:
            c["urgency"] = urg
            c["owner_team"] = owner
            c["theme"] = theme
        excerpt = rev["text"][:140] + ("..." if len(rev["text"]) > 140 else "")
        c["excerpts"].append(f"{int(rev['rating'])}* review: {excerpt}")

    # 3. Process support tickets (Zendesk / HubSpot)
    open_tickets_count = 0
    for tk in tickets:
        c = get_cust(tk["email"], tk["order_id"])
        if tk["is_open"]:
            open_tickets_count += 1
            reason = f"open_ticket_{tk['priority']}"
            if reason not in c["hold_reasons"]:
                c["hold_reasons"].append(reason)
            c["hold_until"] = max(c["hold_until"], ref_day + timedelta(days=14)) if c["hold_until"] else (ref_day + timedelta(days=14))
            theme, text_urg, text_owner = classify_text(f"{tk['subject']} {tk['tags']}")
            tk_urg = 1 if tk["priority"] == "urgent" else (2 if tk["priority"] == "high" else min(3, text_urg))
            if tk_urg < c["urgency"]:
                c["urgency"] = tk_urg
                c["owner_team"] = text_owner
                c["theme"] = theme
            c["excerpts"].append(f"Ticket #{tk['ticket_id']} ({tk['status']}/{tk['priority']}): {tk['subject']}")
        else:
            c["release_eligible"] = True

    # Build final outputs: CRM hold/release CSVs + deduplicated LTV-weighted CS queue
    klaviyo_rows: list[list[object]] = []
    hubspot_rows: list[list[object]] = []
    queue_items: list[dict] = []
    active_holds = 0
    released_holds = 0
    vip_p0_count = 0
    unresolved_no_email = 0

    for key, c in sorted(customers.items()):
        ltv_info = ltv_by_email.get(c["email"], {"orders": 0, "ltv": 0.0, "is_vip": False})
        is_vip = ltv_info["is_vip"]
        ltv = ltv_info["ltv"]

        if c["hold_reasons"]:
            # Determine priority tier combining urgency + VIP LTV
            if (is_vip and c["urgency"] <= 2) or (c["urgency"] == 1 and len(c["hold_reasons"]) >= 2):
                tier = "P0"
                vip_p0_count += 1
            elif c["urgency"] == 1 or is_vip:
                tier = "P1"
            elif c["urgency"] == 2:
                tier = "P2"
            else:
                tier = "P3"

            reasons_str = "; ".join(c["hold_reasons"])
            until_str = c["hold_until"].isoformat() if c["hold_until"] else ""
            if c["email"]:
                active_holds += 1
                klaviyo_rows.append([
                    c["email"], "true", "true", "HOLD", reasons_str, until_str,
                    c["order_id"], c["carrier"], c["days_late"], tier,
                ])
                hubspot_rows.append([
                    c["email"], "Yes", "Yes", "HOLD", reasons_str, until_str,
                    c["order_id"], c["carrier"], tier,
                ])
            else:
                unresolved_no_email += 1

            queue_items.append({
                "tier": tier,
                "tier_rank": int(tier[1]),
                "urgency": c["urgency"],
                "ltv": ltv,
                "is_vip": is_vip,
                "row": [
                    tier,
                    c["owner_team"],
                    c["email"] or f"(missing email: {c['order_id']})",
                    "yes" if is_vip else "no",
                    ltv,
                    c["order_id"],
                    c["carrier"],
                    c["days_late"],
                    reasons_str,
                    c["theme"] or "general_issue",
                    " | ".join(c["excerpts"])[:240],
                ],
            })
        elif c["release_eligible"] and c["email"]:
            released_holds += 1
            klaviyo_rows.append([
                c["email"], "false", "false", "RELEASE", "resolved_after_cooldown", "",
                c["order_id"], c["carrier"], 0, "",
            ])
            hubspot_rows.append([
                c["email"], "No", "No", "RELEASE", "resolved_after_cooldown", "",
                c["order_id"], c["carrier"], "",
            ])

    queue_items.sort(key=lambda x: (x["tier_rank"], -x["ltv"], x["urgency"]))
    queue_rows = [q["row"] for q in queue_items]

    carrier_rows: list[list[object]] = []
    for carrier, st in sorted(carrier_stats.items(), key=lambda kv: (-(kv[1]["late_delivered"] + kv[1]["still_late_open"] + kv[1]["exceptions"]), kv[0])):
        denom = st["delivered"] + st["still_late_open"]
        late_total = st["late_delivered"] + st["still_late_open"]
        late_pct = round((late_total / denom) * 100.0, 1) if denom else 0.0
        avg_delay = round(st["delay_sum"] / st["delay_n"], 1) if st["delay_n"] else 0.0
        carrier_rows.append([
            carrier, st["total"], st["delivered"], st["late_delivered"],
            st["still_late_open"], st["exceptions"], late_pct, avg_delay, st["neg_reviews"],
        ])

    summary = {
        "as_of": ref_day.isoformat(),
        "sources": sources,
        "active_crm_promo_holds": active_holds,
        "released_crm_holds": released_holds,
        "p0_critical_vip_cases": vip_p0_count,
        "total_cs_recovery_queue": len(queue_rows),
        "unresolved_missing_email": unresolved_no_email,
        "shipments_scanned": len(shipments),
        "negative_reviews_triaged": neg_reviews_count,
        "open_support_tickets": open_tickets_count,
    }

    return {
        "summary": summary,
        "klaviyo_header": KLAVIYO_HOLD_HEADER,
        "klaviyo_rows": klaviyo_rows,
        "klaviyo_hold_csv": cio.to_csv_text(KLAVIYO_HOLD_HEADER, klaviyo_rows),
        "hubspot_hold_csv": cio.to_csv_text(HUBSPOT_HOLD_HEADER, hubspot_rows),
        "queue_header": QUEUE_HEADER,
        "queue_rows": queue_rows,
        "cs_queue_csv": cio.to_csv_text(QUEUE_HEADER, queue_rows),
        "carrier_header": CARRIER_HEADER,
        "carrier_rows": carrier_rows,
        "carrier_scorecard_csv": cio.to_csv_text(CARRIER_HEADER, carrier_rows),
    }


def render_cx_report_html(result: dict) -> str:
    s = result["summary"]
    q_head = "".join(f"<th>{escape(h)}</th>" for h in result["queue_header"])
    q_rows = "".join("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in r) + "</tr>" for r in result["queue_rows"])
    c_head = "".join(f"<th>{escape(h)}</th>" for h in result["carrier_header"])
    c_rows = "".join("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in r) + "</tr>" for r in result["carrier_rows"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>CX-to-CRM Daily Operations Brief</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:1180px;margin:28px auto;padding:0 20px;color:#111827}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}}
.card{{border:1px solid #d1d5db;border-radius:10px;padding:12px 14px}}
.card b{{display:block;font-size:24px}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0 24px}}
th,td{{border-bottom:1px solid #e5e7eb;padding:7px 8px;text-align:left}}
</style></head><body>
<h1>CX-to-CRM Promo Guard &amp; Recovery Brief ({escape(s['as_of'])})</h1>
<div class="grid">
  <div class="card"><span>Active CRM Promo Holds</span><b>{s['active_crm_promo_holds']}</b></div>
  <div class="card"><span>CRM Holds Released</span><b>{s['released_crm_holds']}</b></div>
  <div class="card"><span>P0 Critical / VIP Cases</span><b>{s['p0_critical_vip_cases']}</b></div>
  <div class="card"><span>Unified CS Queue</span><b>{s['total_cs_recovery_queue']}</b></div>
</div>
<h2>Unified Customer Service Recovery Queue</h2>
<table><thead><tr>{q_head}</tr></thead><tbody>{q_rows}</tbody></table>
<h2>Carrier SLA Scorecard</h2>
<table><thead><tr>{c_head}</tr></thead><tbody>{c_rows}</tbody></table>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CX-to-CRM Promo Guard & Proactive Recovery Engine.")
    p.add_argument("--shipments", type=Path, help="Carrier / AfterShip / Sendcloud / ShippyPro / Shopify shipments CSV")
    p.add_argument("--reviews", type=Path, help="Trustpilot / Judge.me / Yotpo reviews CSV")
    p.add_argument("--tickets", type=Path, help="Zendesk Support or HubSpot Service Hub Tickets CSV")
    p.add_argument("--orders", type=Path, help="Optional Shopify Orders export (email resolution + VIP LTV)")
    p.add_argument("--as-of", default="", help="Reference date YYYY-MM-DD (default: today)")
    p.add_argument("--late-cooldown", type=int, default=7, help="Days after late delivery before releasing CRM hold")
    p.add_argument("--review-cooldown", type=int, default=30, help="Days to hold promos after a 1-2 star review")
    p.add_argument("--max-rating", type=float, default=2.0, help="Trigger hold at or below this star rating")
    p.add_argument("--out", type=Path, default=Path("build/cx_guard"))
    args = p.parse_args(argv)

    as_of = cio.parse_day(args.as_of) if args.as_of else date.today()
    res = run_cx_guard(
        shipments_path=args.shipments,
        reviews_path=args.reviews,
        tickets_path=args.tickets,
        orders_path=args.orders,
        as_of=as_of,
        late_delivery_cooldown_days=args.late_cooldown,
        review_hold_days=args.review_cooldown,
        max_negative_rating=args.max_rating,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "klaviyo_cx_promo_hold.csv").write_text(res["klaviyo_hold_csv"], encoding="utf-8", newline="\n")
    (args.out / "hubspot_cx_promo_hold.csv").write_text(res["hubspot_hold_csv"], encoding="utf-8", newline="\n")
    (args.out / "cs_recovery_queue.csv").write_text(res["cs_queue_csv"], encoding="utf-8", newline="\n")
    (args.out / "carrier_sla_scorecard.csv").write_text(res["carrier_scorecard_csv"], encoding="utf-8", newline="\n")
    (args.out / "cx_guard_summary.json").write_text(json.dumps(res["summary"], indent=2) + "\n", encoding="utf-8")
    (args.out / "cx_ops_report.html").write_text(render_cx_report_html(res), encoding="utf-8", newline="\n")

    print(json.dumps(res["summary"], indent=2))
    print(f"\nOutputs written to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
