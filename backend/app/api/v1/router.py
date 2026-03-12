"""
Master API router — combines all v1 sub-routers.
"""
from fastapi import APIRouter

from app.api.v1 import auth, google_auth, users, statements, transactions, budgets, dashboard, suggestions, reports, billing

api_router = APIRouter()

api_router.include_router(auth.router,         prefix="/auth",         tags=["Auth"])
api_router.include_router(google_auth.router,  prefix="/auth/google",  tags=["Auth"])
api_router.include_router(users.router,        prefix="/users",        tags=["Users"])
api_router.include_router(statements.router,   prefix="/statements",   tags=["Statements"])
api_router.include_router(transactions.router, prefix="/transactions",  tags=["Transactions"])
api_router.include_router(budgets.router,      prefix="/budgets",      tags=["Budgets"])
api_router.include_router(dashboard.router,    prefix="/dashboard",    tags=["Dashboard"])
api_router.include_router(suggestions.router,  prefix="/suggestions",  tags=["Suggestions"])
api_router.include_router(reports.router,      prefix="/reports",      tags=["Reports"])
api_router.include_router(billing.router,      prefix="/billing",      tags=["Billing"])
