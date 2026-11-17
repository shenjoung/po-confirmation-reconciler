"""Read order lines out of a confirmation that is not a spreadsheet: an email body, a PDF.

Uses Claude with structured outputs, so the reply is guaranteed to be JSON matching
LINES_SCHEMA. Every line must quote the text it came from; lines whose quote cannot be
found in the source are dropped and reported, so a hallucinated row never reaches review.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .model import Line
from .normalize import parse_date, parse_price, sku_key

DEFAULT_MODEL = os.environ.get("PORECONCILE_MODEL", "claude-opus-5-5")

LINES_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "qty": {"type": ["integer", "null"]},
                    "unit_price": {"type": ["string", "null"]},
                    "ship_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                    "description": {"type": "string"},
                    "quote": {"type": "string", "description": "exact text the line was read from"},
                },
                "required": ["sku", "qty", "unit_price", "ship_date", "description", "quote"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "anything the buyer should know that is not a line"},
    },
    "required": ["lines", "notes"],
    "additionalProperties": False,
}

INSTRUCTIONS = """You read vendor order confirmations for a purchasing team.
Return one entry per confirmed order line. Rules:
- sku: the vendor's item / part / model number exactly as printed.
- qty: the quantity the vendor CONFIRMS (not the quantity ordered, if both appear). 0 if the
  line is marked discontinued, cancelled or unavailable. null if no quantity is given.
- unit_price: the per-unit price as printed, including currency; null if absent.
- ship_date: the promised ship or delivery date as YYYY-MM-DD; null if absent.
- quote: copy the exact source text the line was read from, character for character.
Do not invent lines. Do not merge different SKUs. Put remarks that are not lines in notes."""


@dataclass
class Extraction:
    lines: list[Line]
    notes: str = ""
    dropped: list[dict] = field(default_factory=list)   # failed the quote check


def _content_for(path: Path) -> tuple[list[dict], str]:
    """Message content blocks for the source, plus the text used for the quote check."""
    if path.suffix.lower() == ".pdf":
        data = base64.standard_b64encode(path.read_bytes()).decode()
        doc = {"type": "document",
               "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
        return [doc, {"type": "text", "text": INSTRUCTIONS}], ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return [{"type": "text", "text": f"{INSTRUCTIONS}\n\n<confirmation>\n{text}\n</confirmation>"}], text


def _squash(s: str) -> str:
    return " ".join(s.split()).lower()


def parse_response(payload: dict, source_text: str, source_name: str) -> Extraction:
    """Validate the model's JSON. Separate from the API call so it is testable offline."""
    haystack = _squash(source_text)
    lines, dropped = [], []
    for i, item in enumerate(payload.get("lines", []), start=1):
        quote = item.get("quote") or ""
        if haystack and _squash(quote) not in haystack:
            dropped.append({**item, "reason": "quote not found in the source"})
            continue
        if not sku_key(item.get("sku", "")):
            dropped.append({**item, "reason": "empty SKU"})
            continue
        lines.append(Line(
            sku=item["sku"].strip(),
            qty=item.get("qty"),
            unit_price=parse_price(item.get("unit_price")),
            ship_date=parse_date(item.get("ship_date")),
            description=(item.get("description") or "").strip(),
            source=f"{source_name} line {i}: \"{quote.strip()[:80]}\"",
        ))
    return Extraction(lines=lines, notes=payload.get("notes", ""), dropped=dropped)


def extract_lines(path: str | Path, *, client=None, model: str = DEFAULT_MODEL) -> Extraction:
    """Call Claude on a .txt / .eml / .md / .pdf confirmation. Pass `client` to inject a fake."""
    path = Path(path)
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    content, source_text = _content_for(path)
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                 # a safety decline is retried on a fallback model
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": LINES_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined to read {path.name}: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(f"{path.name} produced more lines than fit in one reply; split the file")
    text = next(b.text for b in response.content if b.type == "text")
    return parse_response(json.loads(text), source_text, path.name)
