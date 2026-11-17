"""poreconcile - compare a vendor's order confirmation with your purchase order.

  poreconcile diff PO.csv CONFIRMATION.(csv|xlsx|txt|eml|pdf) [--report r.md] [--changes c.json]
  poreconcile approve c.json --accept 1,3 [--reject 2] [--out approved.csv]
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from .io import read_lines
from .reconcile import reconcile
from .review import (apply_decisions, load_changes, save_changes, to_markdown,
                     write_approved_csv)

TABULAR = {".csv", ".xlsx", ".xlsm"}


def _ids(s: str | None) -> set[int]:
    return {int(x) for x in s.split(",") if x.strip()} if s else set()


def cmd_diff(a) -> int:
    po = read_lines(a.po)
    conf_path = Path(a.confirmation)
    if conf_path.suffix.lower() in TABULAR:
        conf = read_lines(conf_path)
    else:
        from .extract import extract_lines
        ex = extract_lines(conf_path, model=a.model) if a.model else extract_lines(conf_path)
        conf = ex.lines
        if ex.dropped:
            print(f"! {len(ex.dropped)} line(s) dropped: their quoted text is not in the source",
                  file=sys.stderr)
        if ex.notes:
            print(f"Vendor notes: {ex.notes}", file=sys.stderr)
    report = reconcile(po, conf, price_tolerance=Decimal(a.price_tolerance),
                       date_tolerance_days=a.date_tolerance)
    md = to_markdown(report, title=f"Review: {conf_path.name}")
    if a.report:
        Path(a.report).write_text(md)
    else:
        print(md)
    save_changes(report.changes, a.changes)
    print(f"{len(report.changes)} change(s) saved to {a.changes}", file=sys.stderr)
    return 1 if any(c.severity == 3 for c in report.changes) else 0


def cmd_approve(a) -> int:
    changes = apply_decisions(load_changes(a.changes), _ids(a.accept), _ids(a.reject))
    save_changes(changes, a.changes)
    n = write_approved_csv(changes, a.out)
    pending = sum(c.approved is None for c in changes)
    print(f"{n} approved change(s) written to {a.out}; {pending} still unreviewed.")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="poreconcile", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diff", help="compare a confirmation with the PO")
    d.add_argument("po")
    d.add_argument("confirmation")
    d.add_argument("--report", help="write the markdown report here instead of stdout")
    d.add_argument("--changes", default="changes.json")
    d.add_argument("--price-tolerance", default="0.005")
    d.add_argument("--date-tolerance", type=int, default=0, help="days")
    d.add_argument("--model", help="Claude model for non-spreadsheet confirmations")
    d.set_defaults(func=cmd_diff)

    ap = sub.add_parser("approve", help="record a buyer's decisions")
    ap.add_argument("changes")
    ap.add_argument("--accept")
    ap.add_argument("--reject")
    ap.add_argument("--out", default="approved_changes.csv")
    ap.set_defaults(func=cmd_approve)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
