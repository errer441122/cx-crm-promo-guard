# CX-to-CRM Promo Guard & Proactive Recovery Engine

An operational post-purchase bridge connecting **Shipping/Carriers**, **Trustpilot Reviews**, **Zendesk / HubSpot Support**, and **Shopify Orders** directly to **Klaviyo** and **HubSpot CRM**.

**[Launch the browser workbench (zero upload — runs locally via Pyodide)](https://errer441122.github.io/ecommerce-cx-analytics/)**

---

## Operational Gap Covered

Logistics tools, review platforms, and helpdesks know when a customer is frustrated — **your ESP/CRM usually does not**:

- A customer whose parcel has been stuck with a carrier for 5 days still receives your promotional DEM blast and your automated review request — driving unsubscribes, spam complaints, and 1-star public reviews.
- A VIP customer who just left a 1-star Trustpilot review or has an urgent open Zendesk ticket keeps receiving discount newsletters because Support and Marketing sit in disconnected silos.
- Carrier and Trustpilot exports frequently contain an `order_id` / `Reference Id` without an email address, making manual suppression impossible at scale.

This engine runs every morning on unmodified platform CSV exports to **hold promotions & review requests automatically**, **release holds once resolved**, **deduplicate overlapping signals**, and **prioritize Customer Care by customer LTV**.

---

## Day-1 Native Platform Exports Supported

| Silo | Platforms | Native CSV Export Accepted |
| --- | --- | --- |
| **Logistics / Shipping** | **AfterShip**, **Sendcloud**, **ShippyPro**, **Qapla'**, **Shopify Fulfillments**, Carrier CSVs | Auto-detects `Order Number`/`order_id`, `Customer Email`, `Carrier`, `Tracking Status` (`exception`, `failed_attempt`, `lost`, `in_transit`, `delivered`), `Estimated Delivery`, `Delivered At` (falls back to `shipped_at + SLA` when promised date is missing) |
| **Public Reviews** | **Trustpilot Business**, **Judge.me**, **Yotpo**, **Klaviyo Reviews** | Auto-detects `Review Stars`, `Review Title`, `Review Content`, `Reference Id`, `Review Created (UTC)`, `Consumer Email` |
| **Helpdesk / Tickets** | **Zendesk Support**, **HubSpot Service Hub** | Auto-detects Zendesk (`Id`, `Requester email`, `Status`, `Priority`, `Subject`, `Tags`) and HubSpot Tickets (`Ticket ID`, `Associated Contact Email`, `Ticket status`, `Priority`) |
| **Order & LTV Context** | **Shopify** (*Orders > Export*) | Resolves missing emails via `Name -> Email` lookup and calculates historical LTV & VIP status so VIP issues escalate to **P0** |

---

## Immediate Operational Outputs

1. **`klaviyo_cx_promo_hold.csv`** & **`hubspot_cx_promo_hold.csv`** — Ready for bulk import to maintain a **Global Promo Exclusion Segment** (`cx_promo_hold = true`) and **Review-Request Exclusion** (`cx_review_request_hold = true`), including automatic **`RELEASE` (`false`)** rows once late deliveries pass cooldown and tickets close.
2. **`cs_recovery_queue.csv`** — Unified, deduplicated daily Customer Service queue (merges parcel delay + negative review + open ticket for the same customer into one row), ranked by **Priority Tier (`P0`–`P3`) × Customer LTV**, with auditable IT/EN/ES/FR routing (`logistics + customer_service`, `product / quality`, `logistics`, `customer_service`).
3. **`carrier_sla_scorecard.csv`** + **`cx_ops_report.html`** — Carrier SLA scorecard (`late_rate_pct`, open delays, exceptions, average delay days, and linked 1–2 star reviews per carrier) ready for **Power BI**, **Tableau**, **Looker**, or **BigQuery / Snowflake**.

---

## CLI Usage (Pure Python 3.11 Standard Library — Zero Install)

```bash
# Run full cross-tool daily sync (Carrier + Trustpilot + Zendesk + Shopify Orders)
python src/cx_promo_guard.py \
  --shipments fixtures/shipments_carrier_schema.csv \
  --reviews fixtures/trustpilot_reviews_schema.csv \
  --tickets fixtures/zendesk_tickets_schema.csv \
  --orders fixtures/shopify_orders_schema.csv \
  --as-of 2026-06-01 \
  --out build/cx_guard

# Run unit tests
python -m unittest discover -s tests -v
```

---

## Repository Structure

| Path | Purpose |
| --- | --- |
| `src/cx_io.py` | Native CSV auto-parsers for Shopify Orders, multi-carrier shipments, Trustpilot/reviews, Zendesk, and HubSpot Tickets |
| `src/cx_promo_guard.py` | Cross-tool join, CRM hold/release generator, deduplicated LTV-weighted CS queue, and Carrier SLA scorecard |
| `src/web_app.py` & `docs/index.html` | Client-side Pyodide browser workbench (zero server upload) |
| `fixtures/` | Minimal platform schema test fixtures (`example.com` only — no public Olist dataset, no academic regression models) |
| `tests/` | Automated unit tests covering email resolution via Shopify, P0 VIP escalation, hold/release lifecycle, HubSpot tickets, and formula neutralization |

> *Repository note:* Earlier versions of this repository contained an exploratory statistical exercise on the public Olist dataset. That exercise and all Olist CSVs were permanently removed and replaced by this operational CX-to-CRM engine while keeping the repository URL intact.

## License

MIT. See [LICENSE](LICENSE).
