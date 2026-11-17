"""Line-by-line comparison of a vendor confirmation against the purchase order."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from .model import Change, Kind, Line, Report


def _merge(lines: list[Line]) -> dict[str, Line]:
    """Vendors split one SKU over several rows (partial shipments). Sum quantities, keep the
    first price, take the latest ship date."""
    groups: dict[str, list[Line]] = defaultdict(list)
    for ln in lines:
        groups[ln.key].append(ln)
    merged = {}
    for key, group in groups.items():
        first = group[0]
        qtys = [g.qty for g in group if g.qty is not None]
        dates = [g.ship_date for g in group if g.ship_date]
        merged[key] = Line(
            sku=first.sku,
            qty=sum(qtys) if qtys else None,
            unit_price=next((g.unit_price for g in group if g.unit_price is not None), None),
            ship_date=max(dates) if dates else None,
            description=first.description,
            source=", ".join(g.source for g in group if g.source),
        )
    return merged


def reconcile(po: list[Line], confirmation: list[Line], *,
              price_tolerance: Decimal = Decimal("0.005"),
              date_tolerance_days: int = 0) -> Report:
    """Return every difference a buyer has to decide on, most urgent first.

    price_tolerance is absolute (0.005 ignores sub-cent rounding).
    """
    po_by, conf_by = _merge(po), _merge(confirmation)
    changes: list[Change] = []

    def add(kind, ln, **kw):
        changes.append(Change(id=0, kind=kind, sku=ln.sku, evidence=kw.pop("evidence", ln.source), **kw))

    for key, c in conf_by.items():
        p = po_by.get(key)
        if p is None:
            add(Kind.NOT_ORDERED, c, confirmed_value=c.qty,
                note="on the confirmation but not on the PO - do not accept without a buyer")
            continue

        if c.qty is not None and p.qty is not None and c.qty != p.qty:
            if c.qty == 0:
                add(Kind.DISCONTINUED, c, field="qty", po_value=p.qty, confirmed_value=0,
                    note="vendor confirmed zero - discontinued or out of stock?")
            elif c.qty > p.qty:
                add(Kind.OVER_SHIP, c, field="qty", po_value=p.qty, confirmed_value=c.qty,
                    note=f"{c.qty - p.qty} more than ordered")
            else:
                add(Kind.QTY, c, field="qty", po_value=p.qty, confirmed_value=c.qty,
                    note=f"{p.qty - c.qty} short")

        if (c.unit_price is not None and p.unit_price is not None
                and abs(c.unit_price - p.unit_price) > price_tolerance):
            pct = (c.unit_price - p.unit_price) / p.unit_price * 100 if p.unit_price else Decimal(0)
            add(Kind.PRICE, c, field="unit_price", po_value=p.unit_price,
                confirmed_value=c.unit_price, note=f"{pct:+.1f}%")

        if (c.ship_date and p.ship_date
                and abs((c.ship_date - p.ship_date).days) > date_tolerance_days):
            add(Kind.DATE, c, field="ship_date", po_value=p.ship_date, confirmed_value=c.ship_date,
                note=f"{(c.ship_date - p.ship_date).days:+d} days")

    for key, p in po_by.items():
        if key not in conf_by:
            add(Kind.MISSING, p, po_value=p.qty, evidence="",
                note="ordered but the vendor did not confirm it")

    changes.sort(key=lambda ch: (-ch.severity, ch.sku))
    for i, ch in enumerate(changes, start=1):
        ch.id = i
    matched = len(set(po_by) & set(conf_by))
    return Report(po_lines=len(po_by), confirmed_lines=len(conf_by), matched=matched, changes=changes)
