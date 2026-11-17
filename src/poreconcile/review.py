"""Human review: a report to read, and a decision file that only records what a person approved."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .model import Change, Kind, Report

_LABEL = {
    Kind.NOT_ORDERED: "NOT ORDERED", Kind.OVER_SHIP: "OVER-SHIPMENT", Kind.PRICE: "Price",
    Kind.DISCONTINUED: "Discontinued", Kind.MISSING: "Not confirmed", Kind.QTY: "Quantity",
    Kind.DATE: "Ship date",
}


def to_markdown(report: Report, title: str = "Order confirmation review") -> str:
    out = [f"# {title}", "",
           f"PO lines: **{report.po_lines}** · confirmed lines: **{report.confirmed_lines}** · "
           f"matched: **{report.matched}** · changes to review: **{len(report.changes)}**", ""]
    if report.clean:
        out.append("No differences - the confirmation matches the PO.")
        return "\n".join(out) + "\n"
    out += ["| # | Type | SKU | PO | Confirmed | Note | Evidence |",
            "|---|---|---|---|---|---|---|"]
    for ch in report.changes:
        flag = " ⚠️" if ch.severity == 3 else ""
        out.append(f"| {ch.id} | {_LABEL[ch.kind]}{flag} | `{ch.sku}` | {_fmt(ch.po_value)} | "
                   f"{_fmt(ch.confirmed_value)} | {ch.note} | {ch.evidence} |")
    out += ["", "Approve with: `poreconcile approve changes.json --accept 1,2,5`"]
    return "\n".join(out) + "\n"


def _fmt(v) -> str:
    return "—" if v is None else str(v)


def save_changes(changes: list[Change], path: str | Path) -> None:
    Path(path).write_text(json.dumps([c.to_dict() for c in changes], indent=2))


def load_changes(path: str | Path) -> list[Change]:
    items = json.loads(Path(path).read_text())
    return [Change(**{**d, "kind": Kind(d["kind"])}) for d in items]


def apply_decisions(changes: list[Change], accept: set[int], reject: set[int]) -> list[Change]:
    unknown = (accept | reject) - {c.id for c in changes}
    if unknown:
        raise ValueError(f"no change with id {sorted(unknown)}")
    if accept & reject:
        raise ValueError(f"ids both accepted and rejected: {sorted(accept & reject)}")
    for c in changes:
        if c.id in accept:
            c.approved = True
        elif c.id in reject:
            c.approved = False
    return changes


def write_approved_csv(changes: list[Change], path: str | Path) -> int:
    """Only approved field changes go into the file an ERP import would read."""
    rows = [c for c in changes if c.approved and c.field]
    with Path(path).open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["sku", "field", "old_value", "new_value", "evidence"])
        for c in rows:
            w.writerow([c.sku, c.field, c.po_value, c.confirmed_value, c.evidence])
    return len(rows)
