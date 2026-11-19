"""Native CSV readers for Post-Purchase CX, Logistics, Helpdesk, Reviews & Shopify Orders.

Auto-detects unmodified exports from:
- Shopify Orders (Orders > Export) -> order_id -> email lookup & customer LTV / VIP status
- Shipments / Multi-Carrier platforms (AfterShip, Sendcloud, ShippyPro, Qapla', Shopify Fulfillments)
- Reviews platforms (Trustpilot Business, Judge.me, Yotpo, Klaviyo Reviews, generic)
- Support Helpdesks (Zendesk Support, HubSpot Service Hub Tickets)

Handles Excel semicolons, UTF-8 BOM, UTF-16, Windows-1252, decimal commas, ISO and
DD/MM/YYYY dates, and neutralizes CSV formula injection on all exports.

Pure Python standard library (identical execution in CLI and browser via Pyodide).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from pathlib import Path

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d")
NOT_A_SALE = {"refunded", "voided"}

EXCEPTION_STATUSES = {
    "exception",
    "failed_attempt",
    "failed attempt",
    "delivery_failed",
    "lost",
    "damaged",
    "delayed",
    "customs_hold",
    "stuck",
    "returned_to_sender",
    "return_to_sender",
    "address_issue",
}
DELIVERED_STATUSES = {"delivered", "completed"}
OPEN_TICKET_STATUSES = {
    "new",
    "open",
    "pending",
    "hold",
    "on-hold",
    "in progress",
    "waiting on us",
    "waiting on contact",
    "escalated",
}


def safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def norm_order_id(order_id: str | None) -> str:
    return (order_id or "").strip().lstrip("#").upper()


def read_text_tolerant(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = read_text_tolerant(path)
    lines = text.splitlines()
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith("#")):
        start += 1
    body = "\n".join(lines[start:])
    if not body.strip():
        return [], []
    header_line = lines[start]
    delimiter = max(",;\t", key=header_line.count)
    reader = csv.DictReader(io.StringIO(body, newline=""), delimiter=delimiter)
    cols = [c.strip() for c in (reader.fieldnames or [])]
    rows: list[dict[str, str]] = []
    for raw in reader:
        cleaned = {(k.strip() if k else ""): (v or "").strip() for k, v in raw.items()}
        if any(cleaned.values()):
            rows.append(cleaned)
    return cols, rows


def to_csv_text(header: list[str], rows: list[list[object]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for row in rows:
        w.writerow([safe_cell(c) if isinstance(c, str) else c for c in row])
    return buf.getvalue()


def parse_day(text: str | None) -> date | None:
    raw = (text or "").strip()
    if not raw:
        return None
    head = raw.split()[0].split("T")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str | None) -> float:
    cleaned = "".join(ch for ch in (text or "") if ch.isdigit() or ch in ",.-")
    if not cleaned or cleaned in ("-", ".", ","):
        return 0.0
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.rfind(",") > cleaned.rfind(".") else cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def _col(columns: list[str], *candidates: str) -> str | None:
    low_map = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in columns:
            return cand
        if cand.lower() in low_map:
            return low_map[cand.lower()]
    return None


def read_shopify_orders_context(path: Path, vip_min_orders: int = 3, vip_min_spend: float = 300.0) -> tuple[dict[str, str], dict[str, dict]]:
    """Return (order_id_norm -> email, email -> {orders, ltv, is_vip})."""
    cols, rows = read_csv_rows(path)
    is_shopify = {"Name", "Email", "Total"} <= set(cols)
    order_to_email: dict[str, str] = {}
    by_email: dict[str, dict] = {}

    if is_shopify:
        folded: dict[str, dict[str, str]] = {}
        for r in rows:
            name = r.get("Name", "")
            if not name:
                continue
            target = folded.setdefault(name, {})
            for k, v in r.items():
                if v and not target.get(k):
                    target[k] = v
        for name, o in folded.items():
            email = o.get("Email", "").strip().lower()
            if email:
                order_to_email[norm_order_id(name)] = email
            if o.get("Cancelled at") or o.get("Financial Status", "").lower() in NOT_A_SALE:
                continue
            if not email:
                continue
            c = by_email.setdefault(email, {"orders": 0, "ltv": 0.0})
            c["orders"] += 1
            c["ltv"] += parse_amount(o.get("Total"))
    else:
        oid_col = _col(cols, "order_id", "order_number", "Name")
        em_col = _col(cols, "email", "Email")
        val_col = _col(cols, "order_value", "total", "order_value_eur")
        if not em_col:
            raise ValueError("Unrecognised orders CSV: missing Email column.")
        for r in rows:
            email = r.get(em_col, "").strip().lower()
            oid = r.get(oid_col, "") if oid_col else ""
            if email and oid:
                order_to_email[norm_order_id(oid)] = email
            if email:
                c = by_email.setdefault(email, {"orders": 0, "ltv": 0.0})
                c["orders"] += 1
                c["ltv"] += parse_amount(r.get(val_col)) if val_col else 0.0

    for c in by_email.values():
        c["ltv"] = round(c["ltv"], 2)
        c["is_vip"] = c["orders"] >= vip_min_orders or c["ltv"] >= vip_min_spend
    return order_to_email, by_email


def read_shipments(
    path: Path,
    *,
    order_to_email: dict[str, str] | None = None,
    default_sla_days: int = 5,
) -> tuple[str, list[dict]]:
    """Read multi-carrier / AfterShip / Sendcloud / ShippyPro / Shopify fulfillment CSV."""
    cols, rows = read_csv_rows(path)
    oid_col = _col(cols, "order_id", "Order Number", "Order ID", "order_number", "Name", "Reference")
    email_col = _col(cols, "email", "Email", "Customer Email", "Recipient Email")
    carrier_col = _col(cols, "carrier", "Carrier", "Courier", "Shipping Method", "courier_name")
    status_col = _col(cols, "status", "Shipment Status", "Tracking Status", "tag", "Fulfillment Status")
    promised_col = _col(cols, "promised_date", "Estimated Delivery", "Expected Delivery", "promised_delivery_date", "expected_delivery")
    shipped_col = _col(cols, "shipped_date", "shipped_at", "Fulfilled at", "Dispatch Date", "Created at")
    delivered_col = _col(cols, "delivered_date", "delivered_at", "Delivered At", "Delivery Date")
    tracking_col = _col(cols, "tracking_number", "Tracking Number", "AWB")

    if not oid_col and not email_col:
        raise ValueError("Unrecognised shipments CSV: expected order_id/Order Number or email column.")
    if not promised_col and not status_col and not shipped_col:
        raise ValueError("Unrecognised shipments CSV: expected promised_date/Estimated Delivery, status, or shipped_at column.")

    lookup = order_to_email or {}
    fmt = (
        "multi_carrier_export"
        if any(c in cols for c in ("Order Number", "Tracking Status", "Estimated Delivery", "Shipment Status"))
        else ("shopify_fulfillment" if "Fulfilled at" in cols else "carrier_csv")
    )

    out: list[dict] = []
    for r in rows:
        raw_oid = r.get(oid_col, "") if oid_col else ""
        email = (r.get(email_col, "") if email_col else "").strip().lower()
        if not email and raw_oid:
            email = lookup.get(norm_order_id(raw_oid), "")
        status = (r.get(status_col, "") if status_col else "").strip().lower()
        promised = parse_day(r.get(promised_col)) if promised_col else None
        shipped = parse_day(r.get(shipped_col)) if shipped_col else None
        delivered = parse_day(r.get(delivered_col)) if delivered_col else None
        if promised is None and shipped is not None:
            promised = shipped + timedelta(days=default_sla_days)

        is_exception = status in EXCEPTION_STATUSES or any(tok in status for tok in ("exception", "failed", "lost", "delay", "stuck"))
        is_delivered = delivered is not None or status in DELIVERED_STATUSES

        out.append({
            "order_id": raw_oid,
            "order_key": norm_order_id(raw_oid),
            "email": email,
            "carrier": (r.get(carrier_col, "") if carrier_col else "").strip() or "Unknown",
            "tracking_number": (r.get(tracking_col, "") if tracking_col else "").strip(),
            "status": status or ("delivered" if is_delivered else "in_transit"),
            "promised": promised,
            "delivered": delivered,
            "is_exception": is_exception,
            "is_delivered": is_delivered,
        })
    return fmt, out


def read_reviews(path: Path, *, order_to_email: dict[str, str] | None = None) -> tuple[str, list[dict]]:
    """Read native Trustpilot Business, Judge.me, Yotpo, or generic reviews CSV."""
    cols, rows = read_csv_rows(path)
    rating_col = _col(cols, "Review Stars", "rating", "stars", "score", "review_score", "Rating")
    text_col = _col(cols, "Review Content", "body", "comment", "review", "text", "content", "Review Body")
    title_col = _col(cols, "Review Title", "title", "Title")
    date_col = _col(cols, "Review Created (UTC)", "review_date", "created_at", "date", "Date")
    oid_col = _col(cols, "Reference Id", "order_id", "Order ID", "order_number", "order")
    email_col = _col(cols, "Consumer Email", "reviewer_email", "email", "Email")

    if not rating_col or not text_col:
        raise ValueError("Unrecognised reviews CSV: expected Rating/Review Stars and Review Content/body columns.")

    fmt = "trustpilot_business" if "Review Stars" in cols or "Reference Id" in cols else "reviews_csv"
    lookup = order_to_email or {}
    out: list[dict] = []
    for r in rows:
        raw_rating = r.get(rating_col, "").strip()
        if not raw_rating:
            continue
        rating = parse_amount(raw_rating)
        raw_oid = r.get(oid_col, "") if oid_col else ""
        email = (r.get(email_col, "") if email_col else "").strip().lower()
        if not email and raw_oid:
            email = lookup.get(norm_order_id(raw_oid), "")
        text = " ".join(filter(None, [r.get(title_col, "") if title_col else "", r.get(text_col, "")])).strip()
        out.append({
            "rating": rating,
            "text": text,
            "date": parse_day(r.get(date_col)) if date_col else None,
            "order_id": raw_oid,
            "order_key": norm_order_id(raw_oid),
            "email": email,
        })
    return fmt, out


def read_tickets(path: Path, *, order_to_email: dict[str, str] | None = None) -> tuple[str, list[dict]]:
    """Read native Zendesk Support or HubSpot Service Hub Tickets CSV export."""
    cols, rows = read_csv_rows(path)
    id_col = _col(cols, "Id", "Ticket ID", "ticket_id", "id")
    email_col = _col(cols, "Requester email", "Associated Contact Email", "Contact Email", "email", "Email")
    status_col = _col(cols, "Status", "Ticket status", "status")
    prio_col = _col(cols, "Priority", "priority")
    subj_col = _col(cols, "Subject", "Ticket name", "subject", "title")
    tags_col = _col(cols, "Tags", "Category", "tags")
    created_col = _col(cols, "Created at", "Create date", "created_at")
    oid_col = _col(cols, "Order ID", "order_id", "Reference Id")

    if not email_col or not status_col:
        raise ValueError(
            "Unrecognised support tickets CSV: expected Zendesk ('Requester email', 'Status') "
            "or HubSpot Tickets ('Associated Contact Email', 'Ticket status')."
        )

    fmt = "zendesk_support" if "Requester email" in cols else ("hubspot_tickets" if "Ticket status" in cols else "helpdesk_csv")
    lookup = order_to_email or {}
    out: list[dict] = []
    for r in rows:
        raw_oid = r.get(oid_col, "") if oid_col else ""
        email = r.get(email_col, "").strip().lower()
        if not email and raw_oid:
            email = lookup.get(norm_order_id(raw_oid), "")
        if not email:
            continue
        status = r.get(status_col, "").strip().lower()
        is_open = status in OPEN_TICKET_STATUSES or any(k in status for k in ("open", "pending", "hold", "new", "waiting"))
        prio = (r.get(prio_col, "") if prio_col else "normal").strip().lower() or "normal"
        out.append({
            "ticket_id": r.get(id_col, "") if id_col else "",
            "email": email,
            "order_id": raw_oid,
            "status": status,
            "is_open": is_open,
            "priority": prio,
            "subject": r.get(subj_col, "") if subj_col else "",
            "tags": r.get(tags_col, "") if tags_col else "",
            "created": parse_day(r.get(created_col)) if created_col else None,
        })
    return fmt, out
