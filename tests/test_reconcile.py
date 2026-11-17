from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from poreconcile import Kind, Line, read_lines, reconcile
from poreconcile.normalize import parse_date, parse_price, parse_qty, sku_key

EX = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize("raw,key", [
    ("*BR-1001", "BR1001"), ("#BR 1002", "BR1002"), ("br_1002", "BR1002"),
    ("﻿BR-1001", "BR1001"), ("'00123", "00123"), ("  =AB.12 ", "AB12"),
])
def test_sku_key_strips_hidden_prefixes_and_separators(raw, key):
    assert sku_key(raw) == key


@pytest.mark.parametrize("raw,val", [
    ("$1,234.50", Decimal("1234.5")), ("12.00 USD", Decimal("12")), ("2,40 EUR", Decimal("2.4")),
    ("1.234,50", Decimal("1234.5")), ("TBD", None), ("", None), (3.75, Decimal("3.75")),
])
def test_parse_price(raw, val):
    assert parse_price(raw) == (val.quantize(Decimal("0.0001")) if val is not None else None)


def test_parse_qty_and_date():
    assert parse_qty("1,000") == 1000 and parse_qty("-") is None and parse_qty("12 pcs") == 12
    assert parse_date("12/01/2026") == date(2026, 12, 1)
    assert parse_date("Jan 15 2027") == date(2027, 1, 15)
    assert parse_date("soon") is None


def test_reader_finds_header_below_vendor_preamble_and_skips_totals():
    lines = read_lines(EX / "confirmation.csv")
    assert [ln.sku for ln in lines][:2] == ["*BR-1001", "#BR 1002"]
    assert all(not ln.sku.lower().startswith("subtotal") for ln in lines)
    assert lines[0].unit_price == Decimal("1.2000") and lines[0].ship_date == date(2026, 12, 1)


def test_example_files_produce_every_kind_of_change():
    report = reconcile(read_lines(EX / "po.csv"), read_lines(EX / "confirmation.csv"))
    kinds = {(c.kind, c.sku) for c in report.changes}
    assert (Kind.NOT_ORDERED, "GL-9001") in kinds
    assert (Kind.OVER_SHIP, "RF-2001") in kinds
    assert (Kind.PRICE, "MS-3001") in kinds
    assert (Kind.DISCONTINUED, "WA-4001") in kinds
    assert (Kind.MISSING, "CT-5001") in kinds
    assert (Kind.DATE, "*BR-1001") not in kinds          # clean line stays clean
    # split rows for one SKU are merged: 100 + 50 = 150 ordered, so only the date differs
    br2 = [c for c in report.changes if sku_key(c.sku) == "BR1002"]
    assert [c.kind for c in br2] == [Kind.DATE]
    assert report.changes[0].severity == 3                 # most urgent first
    assert [c.id for c in report.changes] == list(range(1, len(report.changes) + 1))


def test_price_tolerance_ignores_rounding():
    po = [Line("A1", qty=1, unit_price=Decimal("1.2000"))]
    conf = [Line("A1", qty=1, unit_price=Decimal("1.2040"))]
    assert reconcile(po, conf).clean
    assert not reconcile(po, conf, price_tolerance=Decimal("0.001")).clean


def test_short_shipment_is_a_quantity_change():
    report = reconcile([Line("A1", qty=10)], [Line("A1", qty=7)])
    (c,) = report.changes
    assert c.kind is Kind.QTY and c.note == "3 short"
