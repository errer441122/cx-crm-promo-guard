# Standard Operating Procedure (SOP): Daily CX-to-CRM Promo Guard

**Owners:** CRM / Marketing Automation & Customer Service Lead  
**Tools:** n8n · Klaviyo / HubSpot · Shopify · Zendesk · Trustpilot · AfterShip / Sendcloud · Slack

---

## 1. Setup Checklist

1. Create custom profile/contact properties in **Klaviyo** and/or **HubSpot**: `cx_promo_hold` (boolean), `cx_review_request_hold` (boolean), `cx_hold_reason` (text), `cx_priority_tier` (text).
2. Create the **`Global Exclusion — Active CX Hold`** segment and attach it to every promotional email template/campaign and to the Post-Purchase Review Request flow.
3. Import [`workflows/cx-promo-guard.n8n.json`](../workflows/cx-promo-guard.n8n.json), [`workflows/cx-hold-release.n8n.json`](../workflows/cx-hold-release.n8n.json), and [`workflows/error-notifier.n8n.json`](../workflows/error-notifier.n8n.json) into n8n, connect credentials, and link the Error Notifier under **Settings → Error Workflow**.
4. *(Optional no-webhook fallback)* If a carrier or review tool does not offer webhooks, upload the daily morning CSV using the ready-made templates in [`templates/`](../templates/).

## 2. Daily Routine (10 Minutes Every Morning)

1. **08:00 — Verify Release Run:** Confirm the 07:30 scheduled release workflow completed cleanly in n8n (no alerts in `#martech-alerts`).
2. **08:05 — Clear P0 VIP Alerts First:** Customer Care handles every `#cx-vip-alerts` item using the pre-drafted Zendesk Internal Note before touching standard tickets.
3. **Before Any Promotional Blast:** CRM Manager confirms `Global Exclusion — Active CX Hold` is selected in the campaign exclusion field.
4. **Weekly Friday Audit:** Export carrier delay counts to identify underperforming couriers before they drag down public Trustpilot scores.
