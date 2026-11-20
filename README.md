# CX-to-CRM AI Promo Guard & Proactive Recovery Workflow

An **n8n + AI Triage + Klaviyo / HubSpot / Zendesk / Shopify** automation blueprint that stops promotional emails and automated review requests from ever reaching customers with a delayed parcel, a 1–2 star Trustpilot review, or an open support ticket — and automatically releases the hold once the issue is resolved.

**[Explore the interactive workflow walkthrough](https://errer441122.github.io/ecommerce-cx-analytics/)** · **[Download Promo Guard n8n blueprint](workflows/cx-promo-guard.n8n.json)** · **[Download Hold Release n8n blueprint](workflows/cx-hold-release.n8n.json)**

---

## The Business Problem

Shipping platforms, Trustpilot, and Zendesk know immediately when a customer is unhappy — **marketing automation tools usually do not**:
- A customer waiting on a stuck parcel still receives your promotional newsletter and your *"How did we do?"* review request, triggering unsubscribes, spam complaints, and 1-star public reviews.
- A VIP customer with an urgent open Zendesk ticket receives a discount blast because Support and CRM operate in separate silos.
- Carrier and review exports frequently identify orders by `order_id` / `Reference Id` without an email address, making manual suppression slow and error-prone.

---

## System Architecture (Two Companion n8n Workflows)

### Workflow 1: Real-Time Hold, AI Triage & VIP Escalation ([`workflows/cx-promo-guard.n8n.json`](workflows/cx-promo-guard.n8n.json))

```mermaid
flowchart LR
    W["1. Webhook: AfterShip / Sendcloud / Trustpilot / Zendesk"] --> SH["2. Shopify Order & VIP LTV Lookup"]
    SH --> AI["3. AI Structured Triage + Empathy Draft (JSON)"]
    AI --> KL["4. Klaviyo: cx_promo_hold = true"]
    AI --> HS["5. HubSpot: CX Promo Hold = Yes"]
    AI --> ZD["6. Zendesk: Private Internal Note (Human Review Only)"]
    KL --> G{"7. P0 Critical or VIP?"}
    G -- "Yes" --> SL["8. Slack #cx-vip-alerts"]
```

### Workflow 2: Daily Cooldown & Automatic Release ([`workflows/cx-hold-release.n8n.json`](workflows/cx-hold-release.n8n.json))

Runs daily at **07:30 CET** so resolved customers are never trapped permanently on a suppression list:
`HOLD (issue active) → COOLDOWN (7d after late delivery / 30d after 1–2★ review) → RELEASE (cx_promo_hold = false)` once zero open tickets remain.

---

## Built-In Operational & AI Safety Guardrails

| Guardrail | How It Works | Reference |
| --- | --- | --- |
| **Human-in-the-loop AI replies** | The AI drafts a concise empathetic response strictly as a **private Zendesk Internal Note** — it never emails frustrated customers autonomously and is explicitly forbidden from promising unapproved refunds or discounts | [`prompts/cx-triage-and-draft-prompt.md`](prompts/cx-triage-and-draft-prompt.md) |
| **VIP P0 escalation & Chargeback detection** | Cross-references Shopify order count/spend (`orders >= 3` or `LTV >= €300`) and scans for chargeback/legal keywords to escalate immediately to `#cx-vip-alerts` | [`workflows/cx-promo-guard.n8n.json`](workflows/cx-promo-guard.n8n.json) |
| **Review-request pause** | Sets `cx_review_request_hold = true` alongside `cx_promo_hold = true`, preventing automated post-purchase review prompts from firing on late parcels | [`docs/state-machine-and-crm-rules.md`](docs/state-machine-and-crm-rules.md) |
| **No-webhook CSV fallback** | Includes ready-to-import Klaviyo & HubSpot CSV suppression templates for teams without carrier webhooks | [`templates/`](templates/) |

---

## Repository Structure

| Path | Content |
| --- | --- |
| `workflows/cx-promo-guard.n8n.json` | 10-node real-time n8n blueprint (Hold + AI Triage + Zendesk Internal Note + VIP Slack Alert) |
| `workflows/cx-hold-release.n8n.json` | 6-node scheduled n8n blueprint handling automatic cooldown release |
| `prompts/cx-triage-and-draft-prompt.md` | Priority rubric (`P0`–`P3`), multilingual triage prompt & brand-safety rules |
| `docs/state-machine-and-crm-rules.md` | State machine (`HOLD → COOLDOWN → RELEASE`) & Klaviyo/HubSpot segment definitions |
| `docs/sop-cx-crm-operations.md` | 1-page daily CRM + Customer Care SOP |
| `templates/` | Ready-to-import Klaviyo & HubSpot CSV suppression templates |
| `docs/index.html` | Interactive visual workflow explorer (GitHub Pages) |

## License

MIT. See [LICENSE](LICENSE).
