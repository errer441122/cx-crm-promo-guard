"""Pyodide browser bridge for docs/index.html (zero server upload)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import cx_io as cio
import cx_promo_guard as guard


def _guarded(fn):
    def run(*args):
        try:
            return json.dumps(fn(*args), default=str)
        except (SystemExit, ValueError, KeyError) as exc:
            return json.dumps({"error": str(exc) or exc.__class__.__name__})
    return run


@_guarded
def run_guard(
    shipments_path: str = "",
    reviews_path: str = "",
    tickets_path: str = "",
    orders_path: str = "",
    as_of: str = "",
    late_cooldown: int = 7,
    review_cooldown: int = 30,
    max_rating: float = 2.0,
) -> dict:
    ref_day = cio.parse_day(as_of) if as_of else date.today()
    res = guard.run_cx_guard(
        shipments_path=Path(shipments_path) if shipments_path else None,
        reviews_path=Path(reviews_path) if reviews_path else None,
        tickets_path=Path(tickets_path) if tickets_path else None,
        orders_path=Path(orders_path) if orders_path else None,
        as_of=ref_day,
        late_delivery_cooldown_days=int(late_cooldown),
        review_hold_days=int(review_cooldown),
        max_negative_rating=float(max_rating),
    )
    res["report_html"] = guard.render_cx_report_html(res)
    return res
