"""
PDF bank statement parser using pdfplumber.

Strategy:
  1. Extract all tables from every page.
  2. Run _detect_columns on each table's header row.
  3. Parse rows that have a valid date + description + amount.
  4. If no tables found, fall back to text-based line parsing (regex).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from app.utils.csv_parser import (   # reuse helpers
    ParsedTransaction,
    CSVParseError,
    _clean_amount,
    _parse_date,
    _detect_columns,
)


class PDFParseError(Exception):
    pass


# ── Table-based extraction ────────────────────────────────────

def _parse_table(table: list[list[str | None]]) -> list[ParsedTransaction]:
    """Parse a single pdfplumber table into ParsedTransaction objects."""
    if not table or len(table) < 2:
        return []

    # First non-empty row as header
    headers = [str(cell or "").strip() for cell in table[0]]
    if not any(headers):
        return []

    try:
        mapping = _detect_columns(headers)
    except CSVParseError:
        return []

    transactions: list[ParsedTransaction] = []
    for row in table[1:]:
        if row is None:
            continue
        cells = [str(c or "").strip() for c in row]
        if not any(cells):
            continue
        if len(cells) < max(mapping.values()) + 1:
            continue

        try:
            raw_date = cells[mapping["date"]]
            raw_desc = cells[mapping["description"]]
            if not raw_date or not raw_desc:
                continue

            txn_date = _parse_date(raw_date)
            desc = re.sub(r"\s+", " ", raw_desc)

            if "amount" in mapping:
                raw_amt = cells[mapping["amount"]]
                if not raw_amt:
                    continue
                amount = _clean_amount(raw_amt)
            else:
                raw_debit = cells[mapping["debit"]].strip() if "debit" in mapping else ""
                raw_credit = cells[mapping["credit"]].strip() if "credit" in mapping else ""
                if raw_debit and raw_debit not in ("0", "0.00", "", "-"):
                    amount = -abs(_clean_amount(raw_debit))
                elif raw_credit and raw_credit not in ("0", "0.00", "", "-"):
                    amount = abs(_clean_amount(raw_credit))
                else:
                    continue

            transactions.append(ParsedTransaction(date=txn_date, description=desc, amount=amount))
        except (CSVParseError, IndexError):
            continue

    return transactions


# ── Text-based fallback ───────────────────────────────────────

# Pattern: date  description  amount (with optional balance)
_LINE_RE = re.compile(
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}[/\-]\d{2}[/\-]\d{2})"   # date
    r"\s+"
    r"(.+?)"                                                               # description
    r"\s+"
    r"([(\-]?\$?[\d,]+\.?\d*\)?)$",                                       # amount
    re.MULTILINE,
)


def _text_fallback(text: str) -> list[ParsedTransaction]:
    """Last-resort: scan raw PDF text for date + description + amount patterns."""
    transactions: list[ParsedTransaction] = []
    for match in _LINE_RE.finditer(text):
        try:
            txn_date = _parse_date(match.group(1))
            desc = re.sub(r"\s+", " ", match.group(2).strip())
            amount = _clean_amount(match.group(3))
            if desc:
                transactions.append(ParsedTransaction(date=txn_date, description=desc, amount=amount))
        except (CSVParseError, Exception):
            continue
    return transactions


# ── Main parse function ───────────────────────────────────────

def parse_pdf(file_bytes: bytes) -> list[ParsedTransaction]:
    """
    Parse a bank statement PDF.
    Returns a list of ParsedTransaction objects.
    Raises PDFParseError if the file cannot be parsed.
    """
    import io as _io

    try:
        pdf_file = _io.BytesIO(file_bytes)
        with pdfplumber.open(pdf_file) as pdf:
            transactions: list[ParsedTransaction] = []
            full_text = ""

            for page in pdf.pages:
                full_text += page.extract_text() or ""
                for table in page.extract_tables():
                    transactions.extend(_parse_table(table))

            # Fallback to text scanning if no table transactions found
            if not transactions and full_text:
                transactions = _text_fallback(full_text)

    except Exception as exc:
        if isinstance(exc, PDFParseError):
            raise
        raise PDFParseError(f"Failed to parse PDF: {exc}") from exc

    if not transactions:
        raise PDFParseError("No transactions found in PDF file")

    return transactions
