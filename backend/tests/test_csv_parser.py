"""
Unit tests for the CSV bank statement parser.
Covers 5 real-world bank export formats plus edge cases.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.utils.csv_parser import CSVParseError, ParsedTransaction, parse_csv


# ── Helpers ───────────────────────────────────────────────────

def _csv(text: str) -> bytes:
    return text.strip().encode("utf-8")


# ── Format 1: Generic (Date, Description, Amount) ─────────────

GENERIC_CSV = _csv("""
Date,Description,Amount
01/15/2025,Whole Foods Market,-52.43
01/16/2025,Employer Payroll,3500.00
01/17/2025,Netflix Subscription,-15.99
01/18/2025,ATM Withdrawal,-100.00
""")


def test_generic_format_basic():
    txns = parse_csv(GENERIC_CSV)
    assert len(txns) == 4
    assert txns[0].date == date(2025, 1, 15)
    assert txns[0].description == "Whole Foods Market"
    assert txns[0].amount == Decimal("-52.43")


def test_generic_format_income():
    txns = parse_csv(GENERIC_CSV)
    payroll = next(t for t in txns if "Payroll" in t.description)
    assert payroll.amount == Decimal("3500.00")


def test_generic_format_count():
    txns = parse_csv(GENERIC_CSV)
    assert len(txns) == 4


# ── Format 2: Chase-style ─────────────────────────────────────

CHASE_CSV = _csv("""
Transaction Date,Post Date,Description,Category,Type,Amount,Memo
01/10/2025,01/11/2025,STARBUCKS #123,Food & Drink,Sale,-6.75,
01/11/2025,01/12/2025,AMAZON.COM,Shopping,Sale,-89.99,Prime membership
01/12/2025,01/13/2025,DIRECT DEPOSIT,Income,Payment,2800.00,Payroll
01/13/2025,01/14/2025,UBER *TRIP,Travel,Sale,-24.50,
""")


def test_chase_format():
    txns = parse_csv(CHASE_CSV)
    assert len(txns) == 4
    starbucks = txns[0]
    assert starbucks.description == "STARBUCKS #123"
    assert starbucks.amount == Decimal("-6.75")
    assert starbucks.date == date(2025, 1, 10)


def test_chase_format_income():
    txns = parse_csv(CHASE_CSV)
    deposit = next(t for t in txns if "DEPOSIT" in t.description)
    assert deposit.amount == Decimal("2800.00")


# ── Format 3: Capital One (split Debit/Credit columns) ────────

CAPITAL_ONE_CSV = _csv("""
Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
2025-01-05,2025-01-06,1234,GROCERY STORE,Groceries,45.20,
2025-01-06,2025-01-07,1234,PAYMENT RECEIVED,Payments,,200.00
2025-01-07,2025-01-08,1234,GAS STATION,Gas/Fuel,38.00,
2025-01-08,2025-01-09,1234,RESTAURANT DINE IN,Dining,55.75,
""")


def test_capital_one_format_debit():
    txns = parse_csv(CAPITAL_ONE_CSV)
    grocery = txns[0]
    assert grocery.amount == Decimal("-45.20")   # debit → negative
    assert grocery.description == "GROCERY STORE"


def test_capital_one_format_credit():
    txns = parse_csv(CAPITAL_ONE_CSV)
    payment = next(t for t in txns if "PAYMENT" in t.description)
    assert payment.amount == Decimal("200.00")   # credit → positive


def test_capital_one_row_count():
    txns = parse_csv(CAPITAL_ONE_CSV)
    assert len(txns) == 4


# ── Format 4: Bank of America ─────────────────────────────────

BOA_CSV = _csv("""
Date,Description,Amount,Running Bal.
01/20/2025,ONLINE TRANSFER CR,-500.00,1500.00
01/21/2025,BILL PAY - ELECTRIC CO,-125.34,1374.66
01/22/2025,ZELLE PAYMENT FROM FRIEND,250.00,1624.66
""")


def test_bank_of_america_format():
    txns = parse_csv(BOA_CSV)
    assert len(txns) == 3
    assert txns[1].description == "BILL PAY - ELECTRIC CO"
    assert txns[1].amount == Decimal("-125.34")


# ── Format 5: ISO date + comma-thousands ──────────────────────

ISO_CSV = _csv("""
date,description,amount
2025-02-01,SALARY TRANSFER,"3,500.00"
2025-02-05,RENT PAYMENT,"-1,200.00"
2025-02-10,SUPERMARKET PURCHASE,-87.30
""")


def test_iso_date_and_thousands_comma():
    txns = parse_csv(ISO_CSV)
    assert txns[0].amount == Decimal("3500.00")
    assert txns[1].amount == Decimal("-1200.00")
    assert txns[0].date == date(2025, 2, 1)


# ── Edge cases ────────────────────────────────────────────────

def test_utf8_bom_header():
    """Files saved from Excel may have a UTF-8 BOM."""
    content = b"\xef\xbb\xbf" + b"Date,Description,Amount\n01/01/2025,Test,-10.00\n"
    txns = parse_csv(content)
    assert len(txns) == 1
    assert txns[0].amount == Decimal("-10.00")


def test_parenthetical_negative():
    csv_bytes = _csv("""
Date,Description,Amount
01/01/2025,Bank Fee,(12.50)
""")
    txns = parse_csv(csv_bytes)
    assert txns[0].amount == Decimal("-12.50")


def test_skips_blank_rows():
    csv_bytes = _csv("""
Date,Description,Amount
01/01/2025,First Transaction,-10.00

01/02/2025,Second Transaction,-20.00
""")
    txns = parse_csv(csv_bytes)
    assert len(txns) == 2


def test_empty_file_raises():
    with pytest.raises(CSVParseError):
        parse_csv(b"")


def test_no_transactions_raises():
    csv_bytes = _csv("Date,Description,Amount\n")
    with pytest.raises(CSVParseError):
        parse_csv(csv_bytes)


def test_dollar_sign_stripped():
    csv_bytes = _csv("""
Date,Description,Amount
01/01/2025,Coffee,$4.75
""")
    txns = parse_csv(csv_bytes)
    assert txns[0].amount == Decimal("4.75")


def test_parsed_transaction_dataclass():
    txn = ParsedTransaction(date=date(2025, 1, 1), description="Test", amount=Decimal("-1.00"))
    assert txn.date == date(2025, 1, 1)
    assert txn.amount < 0
