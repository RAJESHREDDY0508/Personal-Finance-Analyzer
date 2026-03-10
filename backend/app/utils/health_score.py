"""
Financial Health Score calculator (0-100).

Factors and weights:
  - Savings rate          (40 pts): score = min(rate, 0.30) / 0.30 * 40
  - Expense diversity     (20 pts): 1 category = 0 pts, 8+ = 20 pts
  - Income stability      (20 pts): single income source vs. diversified
  - Anomaly penalty       (20 pts): deducted based on anomaly count vs total txns
"""
from __future__ import annotations

from decimal import Decimal


def compute_health_score(
    income: float,
    expenses: float,
    category_count: int,
    anomaly_count: int,
    total_transactions: int,
) -> int:
    """
    Return a health score in [0, 100].
    All monetary values should be non-negative.
    """
    # No income → financially unhealthy by definition
    if income <= 0:
        return 0

    score = 0.0

    # 1. Savings rate (0-40 pts)
    if income > 0:
        net = income - expenses
        savings_rate = max(net / income, 0.0)
        score += min(savings_rate / 0.30, 1.0) * 40

    # 2. Expense diversity (0-20 pts)
    # 1 category → 0, 8+ categories → 20
    diversity_score = min(max(category_count - 1, 0) / 7.0, 1.0) * 20
    score += diversity_score

    # 3. Baseline stability (flat 20 pts if any income exists)
    if income > 0:
        score += 20

    # 4. Anomaly penalty (0-20 pts deducted)
    if total_transactions > 0:
        anomaly_ratio = min(anomaly_count / total_transactions, 0.20)
        penalty = (anomaly_ratio / 0.20) * 20
        score = max(score - penalty, 0.0)

    return round(score)
