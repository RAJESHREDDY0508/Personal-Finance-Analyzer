# Import all models here so Alembic autogenerate can detect them
from app.models.user import User, RefreshToken
from app.models.statement import BankStatement
from app.models.transaction import Transaction
from app.models.budget import Budget
from app.models.suggestion import SavingsSuggestion
from app.models.report import MonthlyReport

__all__ = [
    "User",
    "RefreshToken",
    "BankStatement",
    "Transaction",
    "Budget",
    "SavingsSuggestion",
    "MonthlyReport",
]
