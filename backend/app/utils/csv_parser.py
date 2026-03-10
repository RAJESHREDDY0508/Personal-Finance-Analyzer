"""
CSV bank statement parser.

Handles common US bank export formats:
  - Generic (Date, Description, Amount)
  - Chase (Transaction Date, Post Date, Description, Category, Type, Amount, Memo)
  - Bank of America (Date, Description, Amount, Running Bal.)
  - Wells Fargo (Date, Amount, *, empty, Description)
  - Capital One (Transaction Date, Posted Date, Card No., Description, Category, Debit, Credit)
  - Citi (Date, Description, Debit, Credit)

Normalises every row to (date, description, amount) where:
  amount < 0  → expense / debit
  amount > 0  → income / credit
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


@dataclass
class ParsedTransaction:
    date: date
    description: str
    amount: Decimal   # negative = expense, positive = income


class CSVParseError(Exception):
    pass


# ── Currency helpers ──────────────────────────────────────────

def _clean_amount(raw: str) -> Decimal:
    """
    Convert a raw string amount to Decimal.
    Handles:  1,234.56 | -1,234.56 | (1,234.56) | $1,234.56 | 1.234,56 (EU)
    """
    s = raw.strip()
    # Parenthetical negatives  (1,234.56)  →  -1,234.56
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    # Strip currency symbols
    s = re.sub(r"[£€$¥₹\s]", "", s)
    # EU decimal comma: 1.234,56  →  1234.56  (only if comma is last separator)
    if "," in s and "." in s:
        # e.g.  "1,234.56"  →  keep as is
        s = s.replace(",", "")
    elif "," in s and s.rfind(",") == len(s) - 3:
        # Likely EU: "1.234,56"  →  "1234.56"
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # Thousand separator only: "1,234"  →  "1234"
        s = s.replace(",", "")
    try:
        val = Decimal(s)
    except InvalidOperation as exc:
        raise CSVParseError(f"Cannot parse amount: {raw!r}") from exc
    return -val if negative else val


def _parse_date(raw: str) -> date:
    """Try common date formats."""
    raw = raw.strip()
    for fmt in (
        "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d",
        "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y", "%b %d, %Y",
        "%m-%d-%Y", "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise CSVParseError(f"Cannot parse date: {raw!r}")


# ── Column detection ──────────────────────────────────────────

_DATE_COLS = {"date", "transaction date", "posted date", "post date", "trans date"}
_DESC_COLS = {"description", "memo", "name", "payee", "transaction description", "details"}
_AMOUNT_COLS = {"amount", "transaction amount", "sum", "value"}
_DEBIT_COLS = {"debit", "withdrawal", "charge", "charges"}
_CREDIT_COLS = {"credit", "deposit", "payment"}


def _match(header: str, candidates: set[str]) -> bool:
    return header.strip().lower() in candidates


def _detect_columns(headers: list[str]) -> dict:
    """
    Return a mapping of role → column index.
    Roles: date, description, amount, debit (opt), credit (opt)
    """
    h_lower = [h.strip().lower() for h in headers]
    mapping: dict[str, int] = {}

    for i, h in enumerate(h_lower):
        if h in _DATE_COLS and "date" not in mapping:
            mapping["date"] = i
        elif h in _DESC_COLS and "description" not in mapping:
            mapping["description"] = i
        elif h in _AMOUNT_COLS and "amount" not in mapping:
            mapping["amount"] = i
        elif h in _DEBIT_COLS and "debit" not in mapping:
            mapping["debit"] = i
        elif h in _CREDIT_COLS and "credit" not in mapping:
            mapping["credit"] = i

    # Wells Fargo: positional (Date, Amount, *, *, Description)
    if "date" not in mapping and len(headers) >= 5:
        mapping.setdefault("date", 0)
        mapping.setdefault("amount", 1)
        mapping.setdefault("description", 4)

    missing = {"date", "description"} - mapping.keys()
    if missing:
        raise CSVParseError(f"Could not detect columns: {missing}. Headers: {headers}")
    if "amount" not in mapping and "debit" not in mapping and "credit" not in mapping:
        raise CSVParseError(f"No amount column found. Headers: {headers}")

    return mapping


# ── Main parse function ───────────────────────────────────────

def parse_csv(file_bytes: bytes) -> list[ParsedTransaction]:
    """
    Parse a bank statement CSV file.
    Returns a list of ParsedTransaction objects, skipping empty/header rows.
    Raises CSVParseError on irrecoverable format issues.
    """
    # Detect encoding
    text = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise CSVParseError("Cannot decode file — unsupported encoding")

    # Skip leading non-CSV lines (some banks prepend account info)
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        # Find the first line that looks like a header row
        parts = next(csv.reader([line]))
        lower_parts = [p.strip().lower() for p in parts]
        if any(d in lower_parts for d in _DATE_COLS) or (
            len(parts) >= 3 and any(a in lower_parts for a in _AMOUNT_COLS | _DEBIT_COLS)
        ):
            start = i
            break

    reader = csv.reader(io.StringIO("\n".join(lines[start:])))
    try:
        headers = next(reader)
    except StopIteration:
        raise CSVParseError("File is empty or contains no parseable rows")
    mapping = _detect_columns(headers)

    transactions: list[ParsedTransaction] = []
    errors = 0

    for row_num, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue  # skip blank rows
        if len(row) < max(mapping.values()) + 1:
            continue  # malformed row — skip

        try:
            raw_date = row[mapping["date"]]
            raw_desc = row[mapping["description"]].strip()
            if not raw_date or not raw_desc:
                continue

            txn_date = _parse_date(raw_date)
            desc = re.sub(r"\s+", " ", raw_desc)

            if "amount" in mapping:
                raw_amt = row[mapping["amount"]]
                if not raw_amt.strip():
                    continue
                amount = _clean_amount(raw_amt)
            else:
                # Separate debit / credit columns
                raw_debit = row[mapping["debit"]].strip() if "debit" in mapping else ""
                raw_credit = row[mapping["credit"]].strip() if "credit" in mapping else ""
                if raw_debit and raw_debit not in ("0", "0.00", "", "-"):
                    amount = -abs(_clean_amount(raw_debit))
                elif raw_credit and raw_credit not in ("0", "0.00", "", "-"):
                    amount = abs(_clean_amount(raw_credit))
                else:
                    continue  # both empty → skip

            transactions.append(ParsedTransaction(date=txn_date, description=desc, amount=amount))
        except CSVParseError:
            errors += 1
            if errors > 50:
                raise CSVParseError("Too many parse errors — likely incorrect format")

    if not transactions:
        raise CSVParseError("No transactions found in CSV file")

    return transactions
