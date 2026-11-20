# Standard Operating Procedure (SOP): Daily CX-to-CRM Promo Guard

**Owners:** CRM / Marketing Automation & Customer Service Lead  
**Tools:** n8n · Klaviyo · Shopify · Zendesk · Trustpilot · AfterShip / Sendcloud · Slack

---

## 1. Setup Checklist

1. In **Klaviyo**, build the segment **`CX hold active`** and the conditional split at the top of the review request flow, as described in [`state-machine-and-crm-rules.md`](state-machine-and-crm-rules.md). Add the segment under **Don't send to** on every promotional campaign. The profile properties (`cx_hold_until_delivery`, `cx_hold_until_review`, `cx_hold_until_ticket`, `cx_hold_reason`, `cx_priority_tier`) are created by the first write.
2. Import [`workflows/cx-promo-guard.n8n.json`](../workflows/cx-promo-guard.n8n.json) and [`workflows/error-notifier.n8n.json`](../workflows/error-notifier.n8n.json) into n8n, connect credentials (Shopify, OpenAI or Gemini, Klaviyo, Zendesk, Slack), and link the Error Notifier under **Settings → Error Workflow**.
3. Point the webhooks at the n8n production URL: carrier exceptions (AfterShip / Sendcloud), 1-2 star reviews only (Trustpilot), and every Zendesk ticket update.
4. *(Optional no-webhook fallback)* If a carrier or review tool has no webhooks, import the morning CSV built from [`templates/klaviyo-global-exclusion-template.csv`](../templates/klaviyo-global-exclusion-template.csv).

## 2. Daily Routine (10 Minutes Every Morning)

1. **08:00, check failures:** no failed runs posted in `#martech-alerts`.
2. **08:05, clear P0 and VIP alerts first:** Customer Care handles every `#cx-vip-alerts` item using the drafted Zendesk internal note before touching standard tickets.
3. **Before any promotional campaign:** the CRM owner confirms `CX hold active` is selected under **Don't send to**.
4. **Weekly (Friday):** look at the size of `CX hold active`. A sudden jump usually means a carrier problem; compare exception counts by courier before they drag down public review scores.

There is no release job to monitor: every pause ends on its own date.
