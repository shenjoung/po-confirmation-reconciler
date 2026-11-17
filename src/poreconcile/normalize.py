"""Turning the many ways vendors write SKUs, prices and dates into comparable values."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# Characters vendors (or their ERP exports) put in front of item numbers.
# They are invisible in Excel and make an exact match fail silently.
_PREFIX = re.compile(r"^[\s*#'\"`=+]+")
_SEPARATORS = re.compile(r"[\s\-_./]+")
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿ "), None)


def sku_key(raw: str) -> str:
    """Comparable form of a SKU: no hidden prefixes, separators or case.

    >>> sku_key(" *ab-1001 ")
    'AB1001'
    >>> sku_key("#AB 1001")
    'AB1001'
    """
    s = unicodedata.normalize("NFKC", str(raw)).translate(_ZERO_WIDTH)
    s = _PREFIX.sub("", s.strip())
    return _SEPARATORS.sub("", s).upper()


def parse_qty(raw) -> int | None:
    if raw is None or str(raw).strip() in {"", "-", "n/a", "N/A"}:
        return None
    s = re.sub(r"[^\d.\-]", "", str(raw).replace(",", ""))
    try:
        return int(Decimal(s))
    except (InvalidOperation, ValueError):
        return None


def parse_price(raw) -> Decimal | None:
    """'$1,234.50', '12.00 USD', '1.234,50 EUR' -> Decimal; 'TBD', '' -> None."""
    if raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw)).quantize(Decimal("0.0001"))
    s = re.sub(r"[^\d.,\-]", "", str(raw))
    if not re.search(r"\d", s):
        return None
    if "," in s and "." in s:           # decide which one is the decimal mark
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif s.count(",") == 1 and len(s.split(",")[1]) in (1, 2):
        s = s.replace(",", ".")          # 2,40 -> 2.40
    else:
        s = s.replace(",", "")
    try:
        return Decimal(s).quantize(Decimal("0.0001"))
    except InvalidOperation:
        return None


_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%y", "%d %b %Y", "%b %d %Y",
                 "%b %d, %Y", "%d-%b-%Y", "%Y%m%d")


def parse_date(raw) -> date | None:
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = re.sub(r"\s+", " ", str(raw).strip())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
