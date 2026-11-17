"""Reading order lines from CSV or Excel, whatever the vendor called the columns."""
from __future__ import annotations

import csv
from pathlib import Path

from .model import Line
from .normalize import parse_date, parse_price, parse_qty

# Header spellings seen on real purchase orders and confirmations.
ALIASES = {
    "sku": ["sku", "item", "item no", "item number", "item #", "part", "part no", "part number",
            "model", "model no", "vendor sku", "product code", "code"],
    "qty": ["qty", "quantity", "order qty", "qty ordered", "confirmed qty", "qty confirmed",
            "units", "ship qty"],
    "unit_price": ["unit price", "price", "unit cost", "cost", "net price", "each"],
    "ship_date": ["ship date", "eta", "delivery date", "promise date", "est ship", "ship by",
                  "available date"],
    "description": ["description", "desc", "item description", "product", "name"],
}


def _norm_header(h) -> str:
    return " ".join(str(h or "").lower().replace("_", " ").replace(".", " ").split())


def map_columns(headers: list) -> dict[str, int]:
    """Which column index holds each field. Exact alias match wins over substring."""
    found: dict[str, int] = {}
    normed = [_norm_header(h) for h in headers]
    for field, names in ALIASES.items():
        for i, h in enumerate(normed):
            if h in names and field not in found:
                found[field] = i
    for field, names in ALIASES.items():
        if field in found:
            continue
        for i, h in enumerate(normed):
            if i not in found.values() and any(n in h for n in names):
                found[field] = i
                break
    if "sku" not in found:
        raise ValueError(f"no SKU / item column among headers: {headers}")
    return found


def _rows(path: Path) -> list[list]:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        try:
            from openpyxl import load_workbook
        except ImportError as e:  # pragma: no cover
            raise SystemExit("Reading Excel needs openpyxl: pip install openpyxl") from e
        ws = load_workbook(path, read_only=True, data_only=True).active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.reader(fh))


def read_lines(path: str | Path) -> list[Line]:
    path = Path(path)
    rows = [r for r in _rows(path) if any(str(c or "").strip() for c in r)]
    if not rows:
        return []
    # The header is the first row that has an SKU-like column (vendors put logos/notes above it).
    for h_idx, row in enumerate(rows[:15]):
        try:
            cols = map_columns(row)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"{path.name}: could not find a header row with an SKU column")

    def get(row, field):
        i = cols.get(field)
        return row[i] if i is not None and i < len(row) else None

    lines = []
    for n, row in enumerate(rows[h_idx + 1:], start=h_idx + 2):
        sku = str(get(row, "sku") or "").strip()
        if not sku or sku.lower().startswith(("total", "subtotal")):
            continue
        lines.append(Line(
            sku=sku,
            qty=parse_qty(get(row, "qty")),
            unit_price=parse_price(get(row, "unit_price")),
            ship_date=parse_date(get(row, "ship_date")),
            description=str(get(row, "description") or "").strip(),
            source=f"{path.name} row {n}",
        ))
    return lines
