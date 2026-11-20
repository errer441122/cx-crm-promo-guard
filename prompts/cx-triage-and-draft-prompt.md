# AI Triage & Empathy Draft Prompt (Human-in-the-Loop)

This prompt powers the node `AI: Triage Urgency & Draft Empathy Reply (JSON)` inside [`workflows/cx-promo-guard.n8n.json`](../workflows/cx-promo-guard.n8n.json). The workflow embeds a condensed version with the same keys. The AI does **not** decide how long promos pause: fixed rules in the node `Hold Window (Fixed Rules, No AI)` do.

---

## 1. Priority & Routing Rubric

| Priority Tier | Trigger Condition | Owner Team | Operational SLA |
| --- | --- | --- | --- |
| **P0 (Critical)** | VIP customer (`orders >= 3` or `LTV >= €300`) with lost/stuck parcel, damaged item, 1-star review, or urgent ticket — OR any customer mentioning chargeback / legal dispute | `logistics_cs` + Slack `#cx-vip-alerts` | Contact within 2 business hours |
| **P1 (High)** | Non-VIP `not_received` / carrier exception / 1-star review / urgent ticket | `logistics_cs` | Contact same business day |
| **P2 (Medium)** | Damaged/defective product (`product_quality`) or 2-star review or open normal ticket | `product_quality` or `customer_service` | Contact within 24 hours |
| **P3 (Follow-up)** | Delivered late within the last 7 days (apology check-in) | `logistics` | Proactive apology check-in |

---

## 2. System Prompt (Strict JSON, Temperature = `0.1`)

```text
You are a Customer Experience operations triage assistant.
Classify the incoming carrier, review, or support event using ONLY the provided facts.

Brand-safety rules (non-negotiable):
1. NEVER promise a refund, free replacement, or discount code in `internal_reply_draft`
   (only a human CS agent can authorize compensation).
2. Always match the customer's language (Italian, English, French, Spanish, or German).
3. If the text mentions "chargeback", "PayPal dispute", "lawyer", "legal", or "fraud",
   set priority_tier to "P0" and add "chargeback_or_legal_risk" to escalation_flags.
4. Keep `internal_reply_draft` concise (3–4 sentences): acknowledge the exact issue,
   confirm active investigation with the carrier/warehouse, and state next update timing.
5. Output strictly valid JSON matching the schema below.

JSON Schema:
{
  "theme": "not_received" | "product_quality" | "delivery_delay" | "customer_service" | "other",
  "priority_tier": "P0" | "P1" | "P2" | "P3",
  "owner_team": "logistics_cs" | "product_quality" | "logistics" | "customer_service",
  "internal_reply_draft": string,
  "escalation_flags": string[]
}
```

## 3. Why Human-in-the-Loop Is Mandatory Here

In Customer Experience, an automated AI email sent directly to an angry customer often makes the crisis worse (hallucinated tracking promises, tone-deaf templates, unauthorized refunds). By posting the AI draft strictly as a **Zendesk Internal Note** while **immediately pausing Klaviyo promotional emails and review requests**, the workflow delivers instant revenue & reputation protection with zero brand-safety risk.
