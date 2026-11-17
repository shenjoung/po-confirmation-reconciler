"""Plain data types shared by every step of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class Line:
    """One order line, from either the purchase order or the vendor's confirmation."""
    sku: str                       # as printed
    qty: int | None = None
    unit_price: Decimal | None = None
    ship_date: date | None = None
    description: str = ""
    source: str = ""               # where it came from: "row 7", "page 2", ...

    @property
    def key(self) -> str:
        from .normalize import sku_key
        return sku_key(self.sku)


class Kind(str, Enum):
    QTY = "qty_change"
    PRICE = "price_change"
    DATE = "date_change"
    OVER_SHIP = "over_shipment"      # confirmed more than ordered
    NOT_ORDERED = "not_ordered"      # on the confirmation, not on the PO
    MISSING = "missing_from_confirmation"
    DISCONTINUED = "discontinued"    # confirmed qty is 0


SEVERITY = {  # what needs a human first
    Kind.NOT_ORDERED: 3, Kind.OVER_SHIP: 3, Kind.PRICE: 2,
    Kind.DISCONTINUED: 2, Kind.MISSING: 2, Kind.QTY: 1, Kind.DATE: 1,
}


@dataclass
class Change:
    id: int
    kind: Kind
    sku: str
    field: str = ""
    po_value: object = None
    confirmed_value: object = None
    note: str = ""
    evidence: str = ""             # where on the confirmation it was read
    approved: bool | None = None   # None = not reviewed yet

    @property
    def severity(self) -> int:
        return SEVERITY[self.kind]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        for k in ("po_value", "confirmed_value"):
            if isinstance(d[k], (Decimal, date)):
                d[k] = str(d[k])
        return d


@dataclass
class Report:
    po_lines: int
    confirmed_lines: int
    matched: int
    changes: list[Change] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.changes
