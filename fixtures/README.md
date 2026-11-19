# Schema Test Fixtures

Minimal platform schema fixtures (`example.com` addresses only) used to test cross-tool CSV joining, CRM hold/release outputs, and LTV-prioritized CS triage in CI. They are **not** real customer records or public Olist datasets.

| Fixture | Platform Export Schema Tested |
| --- | --- |
| `shopify_orders_schema.csv` | Shopify Admin → *Orders > Export* (provides `order_id -> email` lookup & VIP LTV enrichment) |
| `shipments_carrier_schema.csv` | Multi-carrier / AfterShip / Sendcloud / ShippyPro export (includes missing email resolved via Shopify, carrier exception, in-transit delay, late delivered) |
| `trustpilot_reviews_schema.csv` | Trustpilot Business CSV export (`Review Stars`, `Reference Id` resolved via Shopify when email is absent) |
| `zendesk_tickets_schema.csv` | Zendesk Support CSV export (`Id`, `Requester email`, `Status`, `Priority`, `Subject`, `Tags`) |
| `hubspot_tickets_schema.csv` | HubSpot Service Hub Tickets CSV export (`Ticket ID`, `Associated Contact Email`, `Ticket status`, `Priority`) |
