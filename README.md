# po-confirmation-reconciler

Vendors confirm purchase orders in every shape: a spreadsheet with a logo and two
lines of notes above the header, item numbers with an invisible `*` or `#` in front,
one SKU split over two rows because half of it is back-ordered, or a plain email
that says "remaining 50 pcs on backorder until Jan 15". A buyer then compares it
line by line with the PO and re-types the differences.

`poreconcile` does the comparison and leaves the decision to the buyer:

1. **Read** the confirmation — CSV/Excel directly, or an email/PDF through Claude
   with structured outputs.
2. **Compare** it with the PO and list every difference, most urgent first.
3. **Approve** — nothing becomes an "approved change" until a person says so.

```text
$ poreconcile diff examples/po.csv examples/confirmation.csv

| # | Type             | SKU        | PO         | Confirmed  | Note                             |
|---|------------------|------------|------------|------------|----------------------------------|
| 1 | NOT ORDERED ⚠️    | GL-9001    | —          | 40         | do not accept without a buyer    |
| 2 | OVER-SHIPMENT ⚠️  | RF-2001    | 500        | 600        | 100 more than ordered            |
| 3 | Not confirmed    | CT-5001    | 1000       | —          | ordered but not confirmed        |
| 4 | Price            | MS-3001    | 3.7500     | 3.9500     | +5.3%                            |
| 5 | Discontinued     | WA-4001    | 120        | 0          | discontinued or out of stock?    |
| 6 | Ship date        | #BR 1002   | 2026-12-01 | 2027-01-15 | +45 days                         |

$ poreconcile approve changes.json --accept 4,6 --reject 2
2 approved change(s) written to approved_changes.csv; 3 still unreviewed.
```

## What it handles

| Problem on real confirmations | How |
|---|---|
| `*BR-1001`, `#BR 1002`, `br_1002`, BOM / zero-width characters | SKUs are compared on a normalized key, shown as printed |
| Header row buried under a vendor preamble; "Subtotal" rows | Header is detected by column names; total rows are skipped |
| Columns called *Item No.*, *Part #*, *Unit Cost*, *ETA*, *Confirmed Qty*… | Alias table maps them to SKU / qty / price / date |
| One SKU split across rows (partial shipments) | Quantities summed, latest date kept, before comparing |
| `$1,234.50`, `12.00 USD`, `2,40 EUR`, `TBD` | Price parser handles both decimal marks; `TBD` is "no price" |
| Sub-cent rounding differences | Configurable price tolerance (default 0.005) |
| Free-text email or PDF confirmation | Claude extracts lines into a JSON schema; each line must quote its source text, and lines whose quote is not in the document are **dropped and reported** |

Severity order: items not on the PO and over-shipments first (they cost money if
accepted by mistake), then price changes, discontinued and unconfirmed lines,
then quantity and date changes. `diff` exits with status 1 when a severity-3
change is present, so it can gate an automated pipeline.

## Install

```bash
pip install -e ".[llm,dev]"     # [llm] only needed for email / PDF confirmations
```

Email/PDF extraction uses the Anthropic API (`ANTHROPIC_API_KEY`, or an
`ant auth login` profile). The model defaults to `claude-opus-5-5`; override with
`--model` or `PORECONCILE_MODEL`. Requests use server-side fallbacks, so a rare
safety decline is retried on a fallback model instead of returning nothing.

```bash
poreconcile diff examples/po.csv examples/confirmation_email.txt --report review.md
```

## Library use

```python
from poreconcile import read_lines, reconcile

report = reconcile(read_lines("po.xlsx"), read_lines("vendor_confirmation.xlsx"))
for change in report.changes:
    print(change.id, change.kind.value, change.sku, change.po_value, "->", change.confirmed_value)
```

## Tests

```bash
python -m pytest
```

25 tests: SKU / price / date normalization, header detection, every change type on
the example files, tolerance handling, the quote check that drops invented lines,
the API request shape (with a fake client, no network), refusal handling, and the
approve → CSV round trip.

## License

MIT
