import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from poreconcile import Kind, read_lines, reconcile
from poreconcile.cli import main
from poreconcile.extract import extract_lines, parse_response
from poreconcile.review import apply_decisions, load_changes, to_markdown, write_approved_csv

EX = Path(__file__).resolve().parent.parent / "examples"
EMAIL = (EX / "confirmation_email.txt").read_text()


def test_lines_whose_quote_is_not_in_the_source_are_dropped():
    payload = {"notes": "", "lines": [
        {"sku": "BR-1001", "qty": 200, "unit_price": "$1.20", "ship_date": "2026-12-01",
         "description": "steel bracket small",
         "quote": "BR-1001 steel bracket small: 200 pcs @ $1.20, ships Dec 1"},
        {"sku": "ZZ-9999", "qty": 5, "unit_price": "$9.00", "ship_date": None,
         "description": "made up", "quote": "ZZ-9999 widget: 5 pcs"},
    ]}
    ex = parse_response(payload, EMAIL, "email.txt")
    assert [ln.sku for ln in ex.lines] == ["BR-1001"]
    assert ex.dropped[0]["sku"] == "ZZ-9999"


class FakeClient:
    """Stands in for anthropic.Anthropic(); records the request, returns canned JSON."""
    def __init__(self, payload, stop_reason="end_turn"):
        self.payload, self.stop_reason, self.calls = payload, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        block = SimpleNamespace(type="text", text=json.dumps(self.payload))
        return SimpleNamespace(content=[block], stop_reason=self.stop_reason, stop_details=None)


def test_extract_lines_sends_schema_and_parses_reply():
    payload = {"notes": "WA-4001 discontinued", "lines": [
        {"sku": "WA-4001", "qty": 0, "unit_price": None, "ship_date": None,
         "description": "wall anchor", "quote": "WA-4001 wall anchor heavy duty: discontinued"}]}
    fake = FakeClient(payload)
    ex = extract_lines(EX / "confirmation_email.txt", client=fake)
    req = fake.calls[0]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["model"] == "claude-opus-5-5"
    assert ex.lines[0].qty == 0 and ex.notes == "WA-4001 discontinued"


def test_refusal_is_raised_not_silently_empty():
    with pytest.raises(RuntimeError, match="declined"):
        extract_lines(EX / "confirmation_email.txt", client=FakeClient({}, stop_reason="refusal"))


def test_only_approved_field_changes_reach_the_import_file(tmp_path):
    report = reconcile(read_lines(EX / "po.csv"), read_lines(EX / "confirmation.csv"))
    price = next(c for c in report.changes if c.kind is Kind.PRICE)
    over = next(c for c in report.changes if c.kind is Kind.OVER_SHIP)
    apply_decisions(report.changes, accept={price.id}, reject={over.id})
    out = tmp_path / "approved.csv"
    assert write_approved_csv(report.changes, out) == 1
    assert "MS-3001,unit_price,3.7500,3.9500" in out.read_text()


def test_unknown_or_conflicting_ids_are_rejected():
    report = reconcile(read_lines(EX / "po.csv"), read_lines(EX / "confirmation.csv"))
    with pytest.raises(ValueError):
        apply_decisions(report.changes, accept={999}, reject=set())
    with pytest.raises(ValueError):
        apply_decisions(report.changes, accept={1}, reject={1})


def test_cli_round_trip(tmp_path, capsys):
    changes, report_md, approved = tmp_path / "c.json", tmp_path / "r.md", tmp_path / "a.csv"
    code = main(["diff", str(EX / "po.csv"), str(EX / "confirmation.csv"),
                 "--changes", str(changes), "--report", str(report_md)])
    assert code == 1                          # an unordered line / over-shipment needs a human
    assert "NOT ORDERED" in report_md.read_text()
    first = load_changes(changes)[0]
    assert main(["approve", str(changes), "--reject", str(first.id), "--out", str(approved)]) == 0
    assert load_changes(changes)[0].approved is False
    assert "No differences" in to_markdown(reconcile([], []))
